import os
import sys
import time
import random
import shutil
import sqlite3
import json
import threading
import ctypes
from ctypes import wintypes
import winreg
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw
import pystray
import requests

# Определение базовой папки
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BUFFER_DIR = os.path.join(BASE_DIR, "buffer")
DB_PATH = os.path.join(BASE_DIR, "history.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "error_log.txt")
BUFFER_SIZE = 20

os.makedirs(BUFFER_DIR, exist_ok=True)

# Настройка типов для Win32 API
ctypes.windll.user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
ctypes.windll.user32.SystemParametersInfoW.restype = wintypes.BOOL

class WallpaperApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Wallpaper Mixer Bot")
        self.root.geometry("500x380")
        self.root.resizable(False, False)
        
        self.stop_event = threading.Event()
        self.is_running = False
        self.tray_icon = None
        
        self.cfg_interval = 5
        self.cfg_save_images = False
        self.cfg_done_dir = ""
        
        self.interval_var = tk.IntVar(value=5)
        self.save_images_var = tk.BooleanVar(value=False)
        self.done_dir_var = tk.StringVar(value="")
        self.autostart_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Статус: Остановлен")
        
        self.init_db()
        self.load_config()
        self.build_ui()
        
        self.root.protocol('WM_DELETE_WINDOW', self.minimize_to_tray)
        self.setup_tray()
        self.update_ui_loop()
        
        if "--autostart" in sys.argv:
            self.root.withdraw()
            self.start_logic()

    def log_error(self, text):
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except Exception:
            pass

    def init_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute('''
            CREATE TABLE IF NOT EXISTS history (
                site TEXT, post_id TEXT, PRIMARY KEY (site, post_id)
            )
        ''')
        conn.commit()
        conn.close()

    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.interval_var.set(cfg.get("interval", 5))
                    self.save_images_var.set(cfg.get("save_images", False))
                    self.done_dir_var.set(cfg.get("done_dir", ""))
                    self.autostart_var.set(cfg.get("autostart", False))
            except Exception as e:
                self.log_error(f"Ошибка загрузки конфига: {e}")

    def save_config(self):
        cfg = {
            "interval": self.interval_var.get(),
            "save_images": self.save_images_var.get(),
            "done_dir": self.done_dir_var.get(),
            "autostart": self.autostart_var.get()
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.log_error(f"Ошибка保存конфига: {e}")

    def toggle_autostart(self):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if self.autostart_var.get():
                exe_path = os.path.abspath(sys.executable)
                winreg.SetValueEx(key, "WallpaperMixerBot", 0, winreg.REG_SZ, f'"{exe_path}" --autostart')
            else:
                try:
                    winreg.DeleteValue(key, "WallpaperMixerBot")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            messagebox.showerror("Ошибка реестра", f"Не удалось настроить автозапуск: {e}")

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.done_dir_var.set(os.path.abspath(folder))

    def build_ui(self):
        frame = tk.LabelFrame(self.root, text=" Настройки конфигурации ", padx=15, pady=15)
        frame.pack(fill="x", padx=15, pady=15)
        
        tk.Label(frame, text="Частота смены обоев (сек):").grid(row=0, column=0, sticky="w", pady=5)
        tk.Entry(frame, textvariable=self.interval_var, width=10).grid(row=0, column=1, sticky="w", padx=10, pady=5)
        
        tk.Checkbutton(frame, text="Сохранять использованные картинки в архив", 
                       variable=self.save_images_var, command=self._toggle_dir_state).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)
        
        tk.Label(frame, text="Путь сохранения архива:").grid(row=2, column=0, sticky="w", pady=5)
        self.entry_dir = tk.Entry(frame, textvariable=self.done_dir_var, width=30)
        self.entry_dir.grid(row=2, column=1, sticky="w", pady=5)
        self.btn_browse = tk.Button(frame, text="Обзор...", command=self.browse_folder)
        self.btn_browse.grid(row=2, column=1, sticky="e", pady=5)
        
        tk.Checkbutton(frame, text="Запускать приложение при включении ПК", 
                       variable=self.autostart_var, command=self.toggle_autostart).grid(row=3, column=0, columnspan=2, sticky="w", pady=5)
        
        self.lbl_status = tk.Label(self.root, textvariable=self.status_var, font=("Arial", 10, "bold"), fg="blue")
        self.lbl_status.pack(pady=5)
        
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        
        self.btn_start = tk.Button(btn_frame, text="ЗАПУСТИТЬ", width=15, bg="#d4edda", fg="#155724", font=("Arial", 10, "bold"), command=self.start_logic)
        self.btn_start.pack(side="left", padx=10)
        
        self.btn_stop = tk.Button(btn_frame, text="ОСТАНОВИТЬ", width=15, bg="#f8d7da", fg="#721c24", font=("Arial", 10, "bold"), command=self.stop_logic, state="disabled")
        self.btn_stop.pack(side="right", padx=10)
        
        self._toggle_dir_state()

    def _toggle_dir_state(self):
        if self.save_images_var.get():
            self.entry_dir.config(state="normal")
            self.btn_browse.config(state="normal")
        else:
            self.entry_dir.config(state="disabled")
            self.btn_browse.config(state="disabled")

    def update_ui_loop(self):
        if self.is_running:
            try:
                count = len([f for f in os.listdir(BUFFER_DIR) if os.path.isfile(os.path.join(BUFFER_DIR, f)) and not f.endswith('.tmp')])
                self.status_var.set(f"Статус: РАБОТАЕТ (Буфер: {count}/{BUFFER_SIZE})")
            except Exception:
                pass
        self.root.after(1000, self.update_ui_loop)

    def start_logic(self):
        if self.save_images_var.get() and not self.done_dir_var.get():
            messagebox.showwarning("Внимание", "Укажите путь к папке сохранения архива!")
            return
            
        if self.interval_var.get() < 1:
            messagebox.showwarning("Внимание", "Интервал не может быть меньше 1 секунды!")
            return

        self.save_config()
        
        self.cfg_interval = int(self.interval_var.get())
        self.cfg_save_images = bool(self.save_images_var.get())
        self.cfg_done_dir = os.path.abspath(self.done_dir_var.get()) if self.done_dir_var.get() else ""
        
        self.is_running = True
        self.stop_event.clear()
        
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(fg="green")
        self.status_var.set("Статус: Инициализация пулов...")
        
        threading.Thread(target=self.downloader_worker, daemon=True).start()
        threading.Thread(target=self.wallpaper_worker, daemon=True).start()

    def stop_logic(self):
        self.is_running = False
        self.stop_event.set()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.lbl_status.config(fg="blue")
        self.status_var.set("Статус: Остановлен")

    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color='#155724')
        dc = ImageDraw.Draw(image)
        dc.rectangle((16, 16, 48, 48), fill='#d4edda')
        return image

    def setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem('Открыть меню', self.show_window_from_tray, default=True),
            pystray.MenuItem('Выход', self.quit_app)
        )
        self.tray_icon = pystray.Icon("wallpaper_bot", self.create_tray_image(), "Wallpaper Mixer Bot", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def minimize_to_tray(self):
        self.root.withdraw()

    def show_window_from_tray(self):
        self.root.deiconify()
        self.root.lift()

    def quit_app(self):
        self.stop_logic()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()
        sys.exit(0)

    def downloader_worker(self):
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        active_sites = ['konachan', 'yandere', 'gelbooru']
        pools = {'konachan': [], 'yandere': [], 'gelbooru': []}
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        while not self.stop_event.is_set():
            try:
                self.stop_event.wait(0.1)
                if self.stop_event.is_set(): break
                
                current_files = [f for f in os.listdir(BUFFER_DIR) if os.path.isfile(os.path.join(BUFFER_DIR, f)) and not f.endswith('.tmp')]
                if len(current_files) >= BUFFER_SIZE:
                    self.stop_event.wait(1.0)
                    continue
                
                if not active_sites:
                    self.stop_event.wait(10.0)
                    active_sites = ['konachan', 'yandere', 'gelbooru']
                    continue
                    
                site = random.choice(active_sites)
                
                if not pools[site]:
                    page = random.randint(1, 300)
                    if site == 'konachan': url = f"https://konachan.com/post.json?limit=100&page={page}"
                    elif site == 'yandere': url = f"https://yande.re/post.json?limit=100&page={page}"
                    elif site == 'gelbooru': url = f"https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&limit=100&pid={page}"
                    
                    try:
                        response = requests.get(url, headers=headers, timeout=(3.0, 7.0))
                        if response.status_code != 200:
                            active_sites.remove(site)
                            continue
                        data = response.json()
                        posts = data if site in ['konachan', 'yandere'] else data.get('post', [])
                        if isinstance(posts, dict): posts = [posts]
                        if posts:
                            random.shuffle(posts)
                            pools[site] = posts
                        else:
                            active_sites.remove(site)
                            continue
                    except Exception as e:
                        self.log_error(f"Сбой парсинга API {site}: {e}")
                        if site in active_sites: active_sites.remove(site)
                        continue
                
                post = pools[site].pop()
                post_id = str(post.get('id'))
                file_url = post.get('file_url')
                
                if not post_id or not file_url: continue
                
                c.execute("SELECT 1 FROM history WHERE site = ? AND post_id = ?", (site, post_id))
                if c.fetchone() is not None: continue
                
                ext = os.path.splitext(file_url.split('?')[0])[1].lower()
                if ext not in ['.jpg', '.jpeg', '.png']: continue
                    
                final_path = os.path.join(BUFFER_DIR, f"{site}_{post_id}{ext}")
                tmp_path = final_path + ".tmp"
                
                start_download_time = time.time()
                download_success = False
                
                try:
                    with requests.get(file_url, headers=headers, timeout=4.0, stream=True) as r:
                        if r.status_code == 200:
                            with open(tmp_path, 'wb') as f:
                                for chunk in r.iter_content(chunk_size=16384):
                                    if self.stop_event.is_set() or (time.time() - start_download_time > 12.0):
                                        raise TimeoutError()
                                    if chunk: f.write(chunk)
                            download_success = True
                except Exception as e:
                    self.log_error(f"Сбой загрузки контента с {site} (ID {post_id}): {e}")
                    if os.path.exists(tmp_path): os.remove(tmp_path)
                    continue

                if download_success:
                    os.rename(tmp_path, final_path)
                    c.execute("INSERT INTO history (site, post_id) VALUES (?, ?)", (site, post_id))
                    conn.commit()
                    self.stop_event.wait(1.0)
            except Exception as e:
                self.log_error(f"Критическая ошибка цикла загрузчика: {e}")
                self.stop_event.wait(2.0)
        conn.close()

    def wallpaper_worker(self):
        SPI_SETDESKWALLPAPER = 20
        SPIF_UPDATEINIFILE = 1
        SPIF_SENDCHANGE = 2
        
        # Фиксация стиля заполнения экрана
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "10")
            winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
            winreg.CloseKey(key)
        except Exception as e:
            self.log_error(f"Не удалось выставить стиль реестра: {e}")

        # Промежуточный кэш-путь на диске C: для обхода ограничений Проводника Windows
        temp_wall_path = os.path.join(os.environ.get('TEMP', BASE_DIR), "win_current_wallpaper.png")

        while not self.stop_event.is_set():
            try:
                start_time = time.time()
                files = [os.path.join(BUFFER_DIR, f) for f in os.listdir(BUFFER_DIR) 
                         if os.path.isfile(os.path.join(BUFFER_DIR, f)) and not f.endswith('.tmp')]
                
                if not files:
                    self.stop_event.wait(0.5)
                    continue
                    
                files.sort(key=os.path.getmtime)
                target_wall = files[0]
                
                # КРИТИЧЕСКИЙ ШАГ: Проецируем файл на диск C:\ во избежание изоляции токенов Explorer
                try:
                    shutil.copy2(os.path.abspath(target_wall), temp_wall_path)
                    api_path = temp_wall_path
                except Exception as e:
                    self.log_error(f"Не удалось перенести картинку в кэш C:\\TEMP: {e}. Применяем напрямую.")
                    api_path = os.path.abspath(target_wall)
                
                # Системный вызов WinAPI
                result = ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, api_path, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
                if not result:
                    win_err = ctypes.GetLastError()
                    self.log_error(f"WinAPI отказал в замене обоев. Код системной ошибки Windows: {win_err}")
                
                elapsed = time.time() - start_time
                sleep_time = max(0.1, self.cfg_interval - elapsed)
                self.stop_event.wait(sleep_time)
                if self.stop_event.is_set(): break
                
                # Постобработка
                if self.cfg_save_images and self.cfg_done_dir:
                    os.makedirs(self.cfg_done_dir, exist_ok=True)
                    dest_path = os.path.join(self.cfg_done_dir, os.path.basename(target_wall))
                    if os.path.exists(dest_path):
                        base, ext = os.path.splitext(os.path.basename(target_wall))
                        dest_path = os.path.join(self.cfg_done_dir, f"{base}_{int(time.time())}{ext}")
                    try:
                        shutil.move(target_wall, dest_path)
                    except Exception as e:
                        self.log_error(f"Не удалось архивировать: {e}")
                else:
                    try:
                        os.remove(target_wall)
                    except Exception as e:
                        self.log_error(f"Не удалось удалить: {e}")
            except Exception as e:
                self.log_error(f"Ошибка применения обоев: {e}")
                self.stop_event.wait(1.0)

if __name__ == "__main__":
    myappid = 'mycompany.myproduct.subproduct.1'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    
    root = tk.Tk()
    app = WallpaperApp(root)
    root.mainloop()