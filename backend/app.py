from flask import Flask, render_template, Response
from gevent import pywsgi
import rosmaster_main
import os
import subprocess
import sys
import threading
import time

RELAY_CMD = "/home/jetson/smartcar/relay_cmd.py"

_original_parse_data = rosmaster_main.MyRosmasterApp.parse_data


def _parse_data_with_relay(self, sk_client, data):
    _original_parse_data(self, sk_client, data)
    if data.startswith("$") and data.endswith("#"):
        subprocess.Popen(["python3", RELAY_CMD, data])


rosmaster_main.MyRosmasterApp.parse_data = _parse_data_with_relay

app = Flask(__name__)
myApp = rosmaster_main.MyRosmasterApp(debug=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/index2')
def index2():
    return render_template('index2.html')

@app.route('/video_feed')
def video_feed():
    if myApp.g_debug:
        print("----------------------------video_feed:0x%02x--------------------------" % myApp.g_camera_type)
    return Response(myApp.mode_handle(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/init')
def init():
    myApp.init_tcp_socket()
    return render_template('init.html')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if str(sys.argv[1]) == "debug":
            myApp.setDebug(True)

    task_mecanum = threading.Thread(target=myApp.thread_mecanum, name="task_mecanum")
    task_mecanum.setDaemon(True)
    task_mecanum.start()

    myApp.init_tcp_socket()

    time.sleep(.1)
    for i in range(3):
        myApp.g_bot.set_beep(60)
        time.sleep(.2)

    print("Version:", myApp.g_bot.get_version())
    print("Waiting for connect to the APP!")

    try:
        server = pywsgi.WSGIServer(('0.0.0.0', 6500), app)
        server.serve_forever()
    except KeyboardInterrupt:
        myApp.g_bot.set_car_motion(0, 0, 0)
        myApp.g_bot.set_beep(0)
        if myApp.g_debug:
            print("-----del g_bot-----")
        del myApp.g_bot
