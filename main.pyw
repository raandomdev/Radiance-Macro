import os, sys, json
import webview
import pyautogui 
import keyboard as kb 
import easyocr
version = "0.0.0"
config = "config.json"
base_path = os.path.dirname(sys.argv[0])
config_path = os.path.join(base_path, config)
html_path = os.path.join(base_path, 'lib/dist/index.html')

def load_config():
    config_path = os.path.join(os.path.dirname(sys.argv[0]), 'config.json')
    if not os.path.exists(config_path):
        default_config = {
            "webhook_url": "https://radiance.io/hook",
            "remote_control_enabled": False,
            "remote_session_key": "radiance-remote-9x3k"
        }
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    else:
        with open(config_path, 'r') as f:
            return json.load(f)
        

def save_config(config):
    config_path = os.path.join(os.path.dirname(sys.argv[0]), 'config.json')
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)


class MainLoop:
    def __init__(self, config=None):
        self.config = config if config is not None else load_config()
        self.API = None
    
    def start(self):
        pass
    def stop(self):
        pass

# API class for pywebview ui ig
class API:
    def __init__(self):
        self.config = load_config()
        self.loop = MainLoop(self.config)
        self.loop.API = self

    def get_config(self):
        return self.config
    
    def start_macro(self):
        print("Starting macro...")
        self.loop.start()
        return {"status": "Macro started"}
    

    def main(self):
        webview.create_window(
            title=f"Radiance Macro {version}"
            , url=html_path
            , width=985
            , height=550
            , resizable=False
            , js_api=self
        )
        webview.start(icon=os.path.join(base_path, 'null.icns'))

if __name__ == "__main__":
    api = API()
    api.main()