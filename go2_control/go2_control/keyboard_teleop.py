"""Điều khiển Go2 bằng bàn phím (giữ phím = đi, buông = dừng).

Bắn TwistStamped vào /cmd_vel_joy (qua twist_mux, priority cao -> đè Nav2).

Phím (KHÔNG cần Enter):
    ↑ / ↓     tiến / lùi        (vx)
    ← / →     đi ngang trái/phải (vy)  — Go2 hỗ trợ
    q / e     xoay trái / phải  (yaw)
    space     dừng ngay
    x / Ctrl-C thoát

Cơ chế: terminal ở chế độ raw nên nhận phím tức thời. GIỮ phím -> hệ điều hành
tự lặp phím liên tục -> vận tốc được giữ. BUÔNG phím -> hết lặp -> sau
`hold_timeout` giây robot tự dừng (dead-man). Bấm phím ngược chiều -> đảo vận
tốc ngay (hãm/lùi lại). Tốc độ chỉnh qua ROS param.
"""
import os
import sys
import select
import termios
import tty
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TwistStamped

HELP = __doc__


class KeyboardTeleop(Node):
    def __init__(self):
        super().__init__("go2_keyboard_teleop")

        self.declare_parameter("cmd_topic", "/cmd_vel_joy")
        self.declare_parameter("frame_id", "base_link")
        self.declare_parameter("lin_speed", 0.4)      # m/s tiến/lùi
        self.declare_parameter("lat_speed", 0.3)      # m/s đi ngang
        self.declare_parameter("ang_speed", 0.8)      # rad/s xoay
        self.declare_parameter("hold_timeout", 0.3)   # s không thấy phím -> dừng
        self.declare_parameter("publish_rate", 50.0)  # Hz

        gp = self.get_parameter
        self.topic = gp("cmd_topic").get_parameter_value().string_value
        self.frame_id = gp("frame_id").get_parameter_value().string_value
        self.lin = gp("lin_speed").get_parameter_value().double_value
        self.lat = gp("lat_speed").get_parameter_value().double_value
        self.ang = gp("ang_speed").get_parameter_value().double_value
        self.hold = gp("hold_timeout").get_parameter_value().double_value
        self.dt = 1.0 / max(gp("publish_rate").get_parameter_value().double_value, 1.0)

        self.pub = self.create_publisher(TwistStamped, self.topic, 10)
        self._vx = self._vy = self._wz = 0.0
        self._last_key = 0.0

        self.get_logger().info(
            f"Keyboard teleop -> {self.topic} "
            f"(lin={self.lin} lat={self.lat} ang={self.ang}, dead-man={self.hold}s)")

    def _apply(self, vx, vy, wz):
        self._vx, self._vy, self._wz = vx, vy, wz
        self._last_key = time.monotonic()

    def _handle(self, keys):
        """keys: chuỗi byte đã đọc trong tick này (đã drain hết)."""
        i, n = 0, len(keys)
        while i < n:
            c = keys[i]
            if c == "\x1b" and i + 2 < n + 1 and keys[i + 1:i + 2] == "[":
                seq = keys[i + 2:i + 3]
                if seq == "A":
                    self._apply(self.lin, 0.0, 0.0)
                elif seq == "B":
                    self._apply(-self.lin, 0.0, 0.0)
                elif seq == "D":
                    self._apply(0.0, self.lat, 0.0)
                elif seq == "C":
                    self._apply(0.0, -self.lat, 0.0)
                i += 3
                continue
            if c in ("q", "Q"):
                self._apply(0.0, 0.0, self.ang)
            elif c in ("e", "E"):
                self._apply(0.0, 0.0, -self.ang)
            elif c == " ":
                self._apply(0.0, 0.0, 0.0)
            elif c in ("x", "X", "\x03"):
                raise KeyboardInterrupt
            i += 1

    def _publish(self):
        # dead-man: quá lâu không thấy phím -> dừng (buông phím = dừng)
        if time.monotonic() - self._last_key > self.hold:
            self._vx = self._vy = self._wz = 0.0
        msg = TwistStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        msg.twist.linear.x = self._vx
        msg.twist.linear.y = self._vy
        msg.twist.angular.z = self._wz
        self.pub.publish(msg)

    def run(self):
        if not sys.stdin.isatty():
            self.get_logger().error(
                "stdin không phải terminal -> không đọc được phím. "
                "Chạy trực tiếp `ros2 run go2_control keyboard_teleop` trong terminal.")
            return
        print(HELP)
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)   # tức thời, không cần Enter
            while rclpy.ok():
                # drain mọi byte đang chờ trong tick này
                buf = ""
                while select.select([fd], [], [], 0)[0]:
                    ch = os.read(fd, 1).decode(errors="ignore")
                    if not ch:
                        break
                    buf += ch
                if buf:
                    self._handle(buf)
                self._publish()
                rclpy.spin_once(self, timeout_sec=0)
                time.sleep(self.dt)
        except KeyboardInterrupt:
            pass
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            # gửi vài lệnh dừng cho chắc
            for _ in range(3):
                self._apply(0.0, 0.0, 0.0)
                self._publish()
                time.sleep(0.01)


def main(args=None):
    rclpy.init(args=args)
    node = KeyboardTeleop()
    try:
        node.run()
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
