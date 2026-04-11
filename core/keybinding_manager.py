import json
import logging

logger = logging.getLogger(__name__)


class KeyBindingManager:
    def __init__(self, config_file):
        self.bindings = {}
        self.load_from_config(config_file)

    def load_from_config(self, config_file):
        # Load keybindings from a configuration file.
        try:
            with open(config_file, 'r') as f:
                self.bindings = json.load(f)
        except Exception as e:
            logger.warning(f"Error loading config: {e}")

    def save_to_config(self, config_file):
        # Save current keybindings to a configuration file.
        try:
            with open(config_file, 'w') as f:
                json.dump(self.bindings, f)
        except Exception as e:
            logger.warning(f"Error saving config: {e}")

    def bind_key(self, key, action):
        if key in self.bindings:
            logger.warning(f"Key conflict for {key}.")
        else:
            self.bindings[key] = action

    def unbind_key(self, key):
        if key in self.bindings:
            del self.bindings[key]
        else:
            logger.warning(f"Key {key} is not bound.")

    def get_action(self, key):
        return self.bindings.get(key, None)

    def list_bindings(self):
        return self.bindings
