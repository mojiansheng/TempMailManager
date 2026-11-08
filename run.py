"""程序入口：启动本地 Web 服务并打开浏览器。"""

import sys
import threading
import webbrowser

from app import create_app
from app.config import APP_NAME, DEBUG, HOST, PORT


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    app = create_app()
    url = f"http://{HOST}:{PORT}/"
    if not DEBUG:
        threading.Timer(1.2, _open_browser, args=(url,)).start()

    print(f"\n{APP_NAME} 已启动：{url}")
    print("按 Ctrl+C 停止服务\n")
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True, use_reloader=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
        sys.exit(0)
