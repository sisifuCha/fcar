#!/usr/bin/env python3
"""Print the common obstacle_alert commands and what each one does."""

import argparse

COMMANDS = [
    {
        "title": "1. 语法检查",
        "command": "python3 -m py_compile obstacle_alert/obstacle_app.py obstacle_alert/src/*.py obstacle_alert/scripts/*.py",
        "explain": "只检查 Python 语法，不启动服务，不操作硬件。",
        "safe": "安全",
    },
    {
        "title": "2. 摄像头检查",
        "command": "python3 obstacle_alert/scripts/check_camera.py --device all --frames 10",
        "explain": "尝试打开 depth/usb/wide 摄像头并读取帧；如果主 app.py 正在占用摄像头，可能失败。",
        "safe": "安全，不控制小车",
    },
    {
        "title": "3. 宿主机雷达检查",
        "command": "python3 obstacle_alert/scripts/check_lidar.py --topic /scan --timeout 5",
        "explain": "在当前系统环境读取 /scan。当前机器宿主机没有 rclpy，所以主要用于以后配置好 ROS2 后测试。",
        "safe": "安全，不控制小车",
    },
    {
        "title": "4. 蜂鸣器 dry-run",
        "command": "python3 obstacle_alert/scripts/check_beep.py",
        "explain": "只打印将要执行的蜂鸣器动作，不会真的响。",
        "safe": "安全，不操作硬件",
    },
    {
        "title": "5. 蜂鸣器真实测试",
        "command": "python3 obstacle_alert/scripts/check_beep.py --execute --duration 60",
        "explain": "调用 Rosmaster.set_beep(60)，蜂鸣器短响，然后关闭蜂鸣器。",
        "safe": "会操作蜂鸣器",
    },
    {
        "title": "6. 停车命令 dry-run",
        "command": "python3 obstacle_alert/scripts/check_motion_stop.py",
        "explain": "只打印将要执行的停车命令，不会真的发给底盘。",
        "safe": "安全，不操作硬件",
    },
    {
        "title": "7. 停车命令真实测试",
        "command": "python3 obstacle_alert/scripts/check_motion_stop.py --execute --method both",
        "explain": "发送 set_car_motion(0,0,0) 和 set_car_run(0,0)。脚本不会让车前进，只发送停车命令。",
        "safe": "会操作底盘停止命令",
    },
    {
        "title": "8. 只检测，不蜂鸣，不停车",
        "command": "python3 obstacle_alert/obstacle_app.py --no-beep --no-stop",
        "explain": "启动雷达检测 HTTP 服务，只更新状态接口；遇到障碍物不会蜂鸣，也不会停车。适合第一步静态验证。",
        "safe": "安全，不操作硬件动作",
    },
    {
        "title": "9. 检测 + 蜂鸣，不停车",
        "command": "python3 obstacle_alert/obstacle_app.py --no-stop",
        "explain": "启动雷达检测 HTTP 服务；DANGER 时蜂鸣器报警，但不发送停车命令。你准备运行的就是这个模式。",
        "safe": "会操作蜂鸣器，不会停车",
    },
    {
        "title": "10. 检测 + 蜂鸣 + 停车保护",
        "command": "python3 obstacle_alert/obstacle_app.py",
        "explain": "启动完整保护服务；DANGER 时蜂鸣器报警，并发送停车命令。小车不会主动前进，但如果 APP/遥控器让车走，它会边走边检测，遇障停车。",
        "safe": "会操作蜂鸣器和底盘停止命令",
    },
    {
        "title": "11. 查询障碍物状态",
        "command": "curl http://127.0.0.1:6511/api/obstacle/status",
        "explain": "查询当前 CLEAR/WARN/DANGER、前方距离、蜂鸣/停车配置等状态。",
        "safe": "安全，只读查询",
    },
    {
        "title": "12. 查询服务健康状态",
        "command": "curl http://127.0.0.1:6511/api/obstacle/health",
        "explain": "检查服务是否运行、雷达数据是否新鲜、Docker 容器名等。",
        "safe": "安全，只读查询",
    },
    {
        "title": "13. 查询配置",
        "command": "curl http://127.0.0.1:6511/api/obstacle/config",
        "explain": "查看当前 warn/danger 阈值、蜂鸣器开关、停车开关等配置。",
        "safe": "安全，只读查询",
    },
    {
        "title": "14. 运行在调试端口 6512",
        "command": "python3 obstacle_alert/obstacle_app.py --no-beep --no-stop --port 6512",
        "explain": "用 6512 端口启动无硬件动作测试服务，避免占用正式 6511 端口。",
        "safe": "安全，不操作硬件动作",
    },
]


def print_commands(filter_text=None):
    for item in COMMANDS:
        blob = f"{item['title']} {item['command']} {item['explain']} {item['safe']}"
        if filter_text and filter_text.lower() not in blob.lower():
            continue
        print(item["title"])
        print(f"命令: {item['command']}")
        print(f"作用: {item['explain']}")
        print(f"安全级别: {item['safe']}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Show obstacle_alert command cheatsheet.")
    parser.add_argument("--filter", help="Only show commands containing this text.")
    args = parser.parse_args()
    print_commands(args.filter)


if __name__ == "__main__":
    main()
