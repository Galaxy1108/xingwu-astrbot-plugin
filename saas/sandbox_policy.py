"""Administrator-managed Agent sandbox policy for SaaS-managed bots."""

from __future__ import annotations

import logging
import platform
import shutil
from typing import Any

logger = logging.getLogger(__name__)

SETTINGS_KEY = "sandbox.policy"
RUNTIMES = {"none", "local", "sandbox"}
BOOTERS = {"docker", "shipyard_neo", "cua"}
DEFAULT_POLICY: dict[str, Any] = {
    "enabled": False,
    "allow_user_config": False,
    "runtime": "none",
    "require_admin": True,
    "booter": "docker",
    "limits": {
        "cpu_seconds": 300,
        "memory_mb": 1024,
        "file_size_mb": 100,
        "open_files": 256,
        "processes": 256,
    },
}


def detect_platform() -> dict[str, Any]:
    system = platform.system().lower()
    if system == "linux":
        path = shutil.which("bwrap")
        return {
            "os": "linux",
            "backend": "bubblewrap",
            "available": bool(path),
            "binary": path or "",
            "hint": "需要安装 bubblewrap（bwrap）；缺失时只能使用 none 或第三方沙盒。",
        }
    if system == "darwin":
        path = "/usr/bin/sandbox-exec"
        available = shutil.which("sandbox-exec", path="/usr/bin") == path
        return {
            "os": "macos",
            "backend": "seatbelt",
            "available": available,
            "binary": path,
            "hint": "使用 macOS Seatbelt；若沙盒被系统策略禁用则不可用。",
        }
    if system == "windows":
        return {
            "os": "windows",
            "backend": "unsupported",
            "available": False,
            "binary": "",
            "hint": "Windows 不支持 AstrBot 本地进程沙盒；可改用 Docker/第三方沙盒，或保持 none。",
        }
    return {
        "os": system or "unknown",
        "backend": "unsupported",
        "available": False,
        "binary": "",
        "hint": "当前操作系统不支持本地进程沙盒。",
    }


def _int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是整数")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是整数") from None
    if number < minimum or number > maximum:
        raise ValueError(f"{name} 必须在 {minimum}–{maximum} 之间")
    return number


def normalize_policy(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    limits = data.get("limits") if isinstance(data.get("limits"), dict) else {}
    runtime = str(data.get("runtime") or "none").strip().lower()
    if runtime not in RUNTIMES:
        runtime = "none"
    booter = str(data.get("booter") or "docker").strip().lower()
    if booter not in BOOTERS:
        booter = "docker"
    merged_limits = dict(DEFAULT_POLICY["limits"])
    bounds = {
        "cpu_seconds": (1, 3600),
        "memory_mb": (64, 16384),
        "file_size_mb": (1, 4096),
        "open_files": (16, 8192),
        "processes": (8, 4096),
    }
    for key, (minimum, maximum) in bounds.items():
        try:
            merged_limits[key] = _int(limits.get(key, merged_limits[key]), key, minimum, maximum)
        except ValueError:
            merged_limits[key] = DEFAULT_POLICY["limits"][key]
    return {
        "enabled": bool(data.get("enabled", False)),
        "allow_user_config": bool(data.get("allow_user_config", False)),
        "runtime": runtime,
        "require_admin": bool(data.get("require_admin", True)),
        "booter": booter,
        "limits": merged_limits,
    }


def validate_policy(policy: dict[str, Any], *, platform_info: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_policy(policy)
    info = platform_info or detect_platform()
    if normalized["enabled"] and normalized["runtime"] == "local" and not info["available"]:
        raise ValueError(
            f"当前平台（{info['os']}）本地沙盒不可用：{info.get('hint') or '缺少沙盒依赖'}"
        )
    return normalized


def config_patch(
    policy: dict[str, Any], *, agent_enabled: bool | None = None
) -> dict[str, Any]:
    """AstrBot config patch applied to a SaaS-managed bot config."""
    enabled = policy.get("enabled") if agent_enabled is None else bool(agent_enabled and policy.get("enabled"))
    runtime = policy["runtime"] if enabled else "none"
    return {
        "provider_settings.computer_use_runtime": runtime,
        "provider_settings.computer_use_require_admin": bool(policy.get("require_admin", True)),
        "provider_settings.sandbox.booter": policy.get("booter", "docker"),
    }


def install_runtime_limits(policy: dict[str, Any]) -> bool:
    """Patch AstrBot's local sandbox limits (best-effort, in-process only)."""
    if not policy.get("enabled") or policy.get("runtime") != "local":
        return False
    limits = normalize_policy(policy)["limits"]
    try:
        from astrbot.core.computer.process_sandbox.base import SandboxLimits

        original_init = getattr(SandboxLimits, "_saas_original_init", None)
        if original_init is None:
            original_init = SandboxLimits.__init__
            SandboxLimits._saas_original_init = original_init  # type: ignore[attr-defined]

        def patched_init(self, *args, **kwargs):
            names = ["cpu_seconds", "file_size_bytes", "memory_bytes", "open_files", "processes"]
            if not args and not kwargs:
                kwargs = {
                    "cpu_seconds": int(limits["cpu_seconds"]),
                    "file_size_bytes": int(limits["file_size_mb"]) * 1024 * 1024,
                    "memory_bytes": int(limits["memory_mb"]) * 1024 * 1024,
                    "open_files": int(limits["open_files"]),
                    "processes": int(limits["processes"]),
                }
            return original_init(self, *args, **kwargs)

        SandboxLimits.__init__ = patched_init  # type: ignore[assignment]
        return True
    except Exception:  # noqa: BLE001
        logger.warning("安装 Agent 沙盒资源限制失败", exc_info=True)
        return False


__all__ = [
    "BOOTERS",
    "DEFAULT_POLICY",
    "RUNTIMES",
    "SETTINGS_KEY",
    "config_patch",
    "detect_platform",
    "install_runtime_limits",
    "normalize_policy",
    "validate_policy",
]
