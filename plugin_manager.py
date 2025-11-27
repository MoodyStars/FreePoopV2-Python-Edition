# plugin_manager.py
"""
Simple Plugin Manager for FreePoop V2
- Plugins live in a "plugins" directory next to this file (or provide custom path).
- Each plugin is a .py file that should expose:
    PLUGIN_NAME = "unique_name"
    PLUGIN_DESC = "short description"  # optional
    def is_compatible(adaptor) -> bool:  # optional
        ...
    def initialize(adaptor) -> None:  # optional
        ...
    def on_before_export(adaptor, cmd_list) -> None:  # optional
        # mutate cmd_list or adaptor as needed
        ...
    def run(adaptor, **kwargs) -> Any:  # optional
        ...
- Enabled plugins are tracked in a .plugins.json file in cwd by default.
"""
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Optional, List, Any


class PluginLoadError(Exception):
    pass


class Plugin:
    def __init__(self, path: Path):
        self.path = path
        self.module: Optional[ModuleType] = None
        self.name: str = path.stem
        self.meta: Dict[str, Any] = {}
        self.available: bool = False

    def load(self):
        spec = importlib.util.spec_from_file_location(f"freepoop_plugins.{self.path.stem}", str(self.path))
        if spec is None:
            raise PluginLoadError(f"Could not build spec for plugin {self.path}")
        mod = importlib.util.module_from_spec(spec)
        loader = spec.loader
        if loader is None:
            raise PluginLoadError(f"No loader for plugin {self.path}")
        loader.exec_module(mod)  # type: ignore
        self.module = mod
        # determine canonical name
        self.name = getattr(mod, "PLUGIN_NAME", self.path.stem)
        self.meta["desc"] = getattr(mod, "PLUGIN_DESC", "")
        self.available = True

    def call_hook(self, hook_name: str, *args, **kwargs):
        if not self.available or self.module is None:
            return None
        fn = getattr(self.module, hook_name, None)
        if callable(fn):
            return fn(*args, **kwargs)
        return None


class PluginManager:
    def __init__(self, adaptor=None, plugins_dir: Optional[str] = None, config_path: Optional[str] = None):
        self.adaptor = adaptor
        self.root = Path(plugins_dir or (Path(__file__).parent / "plugins"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = Path(config_path or Path.cwd() / ".plugins.json")
        self.plugins: Dict[str, Plugin] = {}
        self.enabled: Dict[str, bool] = {}
        self._load_config()
        self.discover()

    def _load_config(self):
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.enabled = data.get("enabled", {})
            except Exception:
                self.enabled = {}
        else:
            self.enabled = {}

    def _save_config(self):
        try:
            self.config_path.write_text(json.dumps({"enabled": self.enabled}, indent=2), encoding="utf-8")
        except Exception:
            pass

    def discover(self):
        """
        Scan the plugins directory for .py files and load metadata.
        """
        self.plugins = {}
        for p in sorted(self.root.glob("*.py")):
            try:
                plugin = Plugin(p)
                plugin.load()
                self.plugins[plugin.name] = plugin
                # ensure enabled map has key (default disabled)
                if plugin.name not in self.enabled:
                    self.enabled[plugin.name] = False
            except Exception as e:
                # ignore failing plugin file but keep scanning
                print(f"[plugin_manager] failed to load plugin {p}: {e}", file=sys.stderr)

    def list_plugins(self) -> List[str]:
        return list(self.plugins.keys())

    def plugin_info(self, name: str) -> Dict[str, Any]:
        p = self.plugins.get(name)
        if not p:
            raise KeyError("Plugin not found: " + name)
        return {"name": p.name, "desc": p.meta.get("desc", ""), "available": p.available, "enabled": self.enabled.get(p.name, False)}

    def is_enabled(self, name: str) -> bool:
        return bool(self.enabled.get(name, False))

    def enable(self, name: str):
        if name not in self.plugins:
            raise KeyError("Plugin not found: " + name)
        self.enabled[name] = True
        self._save_config()
        # call initialize hook if present
        plugin = self.plugins[name]
        try:
            plugin.call_hook("initialize", self.adaptor)
        except Exception as e:
            print(f"[plugin_manager] plugin {name} initialize error: {e}", file=sys.stderr)

    def disable(self, name: str):
        if name not in self.plugins:
            raise KeyError("Plugin not found: " + name)
        self.enabled[name] = False
        self._save_config()
        try:
            self.plugins[name].call_hook("on_disable", self.adaptor)
        except Exception:
            pass

    def run(self, name: str, *args, **kwargs) -> Any:
        """
        Call a plugin's run(adaptor, **kwargs) function and return result.
        """
        if name not in self.plugins:
            raise KeyError("Plugin not found: " + name)
        if not self.is_enabled(name):
            raise RuntimeError("Plugin not enabled: " + name)
        plugin = self.plugins[name]
        return plugin.call_hook("run", self.adaptor, **kwargs)

    def run_hook_all(self, hook_name: str, *args, **kwargs):
        """
        Run a named hook on all enabled plugins (e.g., 'on_before_export'), in discovery order.
        """
        for name, plugin in self.plugins.items():
            if not self.is_enabled(name):
                continue
            try:
                plugin.call_hook(hook_name, *args, **kwargs)
            except Exception as e:
                print(f"[plugin_manager] plugin {name} hook {hook_name} error: {e}", file=sys.stderr)