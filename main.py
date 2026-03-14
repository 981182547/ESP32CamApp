import cv2
import threading
import time
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.network.urlrequest import UrlRequest

class ESP32CamApp(App):
    def build(self):
        # 初始化核心变量
        self.capture = None
        self.is_streaming = False
        self.latest_frame = None  # 信箱：用于后台线程向主界面传递处理好的画面
        
        # 加载 OpenCV 电脑自带的轻量级人脸检测模型
        self.face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml')
        self.sensor_event = None 

        font_kwargs = {'font_name': 'MSYH.TTC'}  # 确保你的同级目录下有微软雅黑字体文件，或者电脑自带

        # ================= 界面布局设计 =================
        main_layout = BoxLayout(orientation='vertical', padding=10, spacing=10)

        # 1. 顶部区域：IP输入框 + 连接按钮
        top_layout = BoxLayout(orientation='horizontal', size_hint_y=0.1, spacing=10)
        self.ip_input = TextInput(text="192.168.50.130", multiline=False, font_size=24)
        self.connect_btn = Button(text="连接摄像头", **font_kwargs)
        self.connect_btn.bind(on_press=self.connect_camera)
        
        top_layout.add_widget(self.ip_input)
        top_layout.add_widget(self.connect_btn)

        # 2. 中间区域：视频显示
        self.img_widget = Image(size_hint_y=0.7)

        # 3. 底部区域：状态数据 + 控制按钮
        bottom_layout = BoxLayout(orientation='horizontal', size_hint_y=0.2, spacing=10)
        self.status_label = Label(text="请在上方输入IP并点击连接\n光敏: -- | 烟雾: --", halign="center", **font_kwargs)
        self.light_btn = Button(text="开/关 灯", **font_kwargs)
        self.light_btn.bind(on_press=self.toggle_light)
        
        bottom_layout.add_widget(self.status_label)
        bottom_layout.add_widget(self.light_btn)

        main_layout.add_widget(top_layout)
        main_layout.add_widget(self.img_widget)
        main_layout.add_widget(bottom_layout)

        # 启动主线程定时器：每秒 30 次去“信箱”拿处理好的照片贴到屏幕上，主界面零负担
        Clock.schedule_interval(self.update_ui_frame, 1.0 / 30.0)

        return main_layout

    # ================= 视频流逻辑 (多线程解耦) =================
    def connect_camera(self, instance):
        ip = self.ip_input.text.strip()
        self.stream_url = f"http://{ip}:81/stream"
        
        self.status_label.text = f"正在后台连接: {ip}...\n请稍等！"
        
        # 安全机制：如果已经连着，先发信号停掉旧的后台线程
        self.is_streaming = False
        time.sleep(0.2) 
        
        self.is_streaming = True
        
        # 开启后台“打工人”线程：专门处理网络请求和 AI 计算
        threading.Thread(target=self.video_worker_thread, daemon=True).start()

        # 开启定时获取传感器数据的任务 (每 2 秒获取一次)
        if self.sensor_event:
            self.sensor_event.cancel()
        self.sensor_event = Clock.schedule_interval(self.fetch_sensor_data, 2.0)

    def video_worker_thread(self):
        """这是运行在后台的线程，网络再卡、AI 算得再慢，也影响不到前面的按钮和文字"""
        if self.capture is not None:
            self.capture.release()
            
        # 这里哪怕连接超时卡上几秒钟，主界面也完全不会死机
        self.capture = cv2.VideoCapture(self.stream_url)
        
        while self.is_streaming:
            ret, frame = self.capture.read()
            if ret:
                # 1. 翻转物理倒置的画面
                frame = cv2.flip(frame, -1)
                
                # 2. AI 人脸检测画框
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(gray, 1.1, 5)
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                
                # 3. 将画好框的完美画面，丢进“信箱”
                self.latest_frame = frame
            else:
                # 没拿到画面时稍微休息，防止吃满 CPU
                time.sleep(0.05)
                
        if self.capture is not None:
            self.capture.release()

    def update_ui_frame(self, dt):
        """主界面定时器：无脑从‘信箱’取画贴图"""
        if self.latest_frame is not None:
            # 拷贝一份，防止渲染时后台线程恰好在修改它
            frame = self.latest_frame.copy() 
            
            # 转成 Kivy 能识别的 Texture
            buffer = cv2.flip(frame, 0).tobytes()
            texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='bgr')
            texture.blit_buffer(buffer, colorfmt='bgr', bufferfmt='ubyte')
            
            self.img_widget.texture = texture

    # ================= 传感器与控制逻辑 =================
    def fetch_sensor_data(self, dt):
        """后台静默获取传感器数据"""
        ip = self.ip_input.text.strip()
        url = f"http://{ip}/sensor_status"
        UrlRequest(url, on_success=self.update_sensor_label, timeout=3)

    def update_sensor_label(self, req, result):
        try:
            light = result.get("light", "--")
            smoke = result.get("smoke", "--")
            lamp = result.get("lamp", "--")
            self.status_label.text = f"连接正常 | 继电器灯光: {lamp}\n光敏: {light} | 烟雾: {smoke}"
        except Exception as e:
            print(f"数据解析出错: {e}")

    def toggle_light(self, instance):
        ip = self.ip_input.text.strip()
        url = f"http://{ip}/action?cmd=toggle_light"
        self.status_label.text = "正在发送指令..."
        UrlRequest(url)

if __name__ == '__main__':
    ESP32CamApp().run()