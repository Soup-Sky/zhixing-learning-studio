"""Developer launcher: starts the service and opens the web page. Keys are managed in the web settings page."""
import os
from pathlib import Path
import sys
import threading
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from credential_vault import WindowsVault
from desktop import URL,build_service,open_when_ready,our_service_running,port_busy

def main():
    if port_busy():
        if our_service_running():
            webbrowser.open(URL);return
        raise SystemExit('8877端口已有旧版服务或其他程序。请关闭原启动窗口后重新双击启动器。')
    print('知行 · AI学习工作室\n浏览器将打开登录页面；DeepSeek 密钥在“设置”页面由管理员填写。\n关闭本窗口或在网页“设置”中点“退出程序”即可停止服务。')
    database=Path(os.getenv('LEARNING_DB',str(ROOT/'data'/'learning.sqlite')))
    vault=WindowsVault() if sys.platform=='win32' else None
    _,server=build_service(database,vault)
    threading.Thread(target=open_when_ready,args=(server,),daemon=True).start()
    server.run()

if __name__=='__main__':main()
