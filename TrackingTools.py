import tkinter as tk
import tkinter.ttk as ttk
import tkinter.messagebox
import aiohttp
import asyncio
import time
import threading
import random
from queue import Queue, Empty
import pyautogui
import winsound
import pygetwindow as gw
import collections
from datetime import datetime, timedelta
from enum import Enum

# Global variables
previous_auctions = set()
TARGET_PERCENTAGE = 5
MIN_PROFITS = 500000
MIN_VOLUME = 5
TOTAL_CHECKED = 0

# Global variables
previous_auctions = set()
PROFIT_BASE = 'lowest_bin'

PROXY_LIST = [
    "45.127.248.127:5128",
    "64.64.118.149:6732",
    "167.160.180.203:6754",
    "166.88.58.10:5735",
    "173.0.9.70:5653",
    "45.151.162.198:6600",
    "204.44.69.89:6342",
    "173.0.9.209:5792",
    "206.41.172.74:6634"
]

proxy_queue = collections.deque(PROXY_LIST)

async def fetch_data(session, item_byte):
    url = 'https://sky.coflnet.com/api/price/nbt'
    headers = {'accept': 'text/plain', 'Content-Type': 'application/json'}
    
    while True:
        if not proxy_queue:
            proxy_queue.extend(PROXY_LIST)  # Refill the proxy queue
            continue
        
        proxy = proxy_queue.popleft()
        try:
            async with session.post(url, headers=headers, json={'fullInventoryNbt': item_byte}, proxy=f"http://lzdqmozk:6ya1ww66ld58@{proxy}") as response:
                response.raise_for_status()
                data = await response.json()
                proxy_queue.append(proxy)  # Rotate proxy back to the end of the queue
                return data[0]
        except aiohttp.ClientError as e:
            print(f"Failed with proxy {proxy}: {e}. Retrying...")
            proxy_queue.appendleft(proxy)  # Rotate proxy back to the front of the queue


async def fetch_auctions(session):
    url = 'https://api.hypixel.net/v2/skyblock/auctions'
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
            return data.get('auctions', [])
    except aiohttp.ClientError as e:
        print(f"Failed to fetch auctions: {e}")
        return []

def format_time(timestamp):
    date = datetime.fromtimestamp(timestamp / 1000)
    return date.strftime('%H:%M:%S')

def format_millions(amount):
    return f"{amount / 1000000:.1f}m"

async def check_auction(session, auction, queue, tracking_queue):
    previous_auctions.add(auction['uuid'])
    data = await fetch_data(session, auction['item_bytes'])
    
    if not data:
        tracking_queue.put(f"Pass: {auction['item_name']} - No data fetched")
        return
    
    starting_bid = auction['starting_bid']
    median_price = data['median']
    lowest_bin = data['lbin']
    volume = int(data['volume'])

    profits = 0
    percentage = 0
    
    if PROFIT_BASE == 'lowest_bin' and lowest_bin > 0:
        percentage = ((lowest_bin - starting_bid) / starting_bid) * 100
        profits = (lowest_bin - starting_bid - 1000 - lowest_bin*0.035)
        if starting_bid > lowest_bin:
            tracking_queue.put(f"Pass: {auction['item_name']} - Price higher than lbin ({format_millions(starting_bid)} > {format_millions(lowest_bin)})")
            return
    elif PROFIT_BASE == 'median_price' and median_price > 0:
        percentage = ((median_price - starting_bid) / starting_bid) * 100
        profits = (median_price - starting_bid - 1000 - lowest_bin*0.035)
        if starting_bid > median_price:
            tracking_queue.put(f"Pass: {auction['item_name']} - Price higher than median price ({format_millions(starting_bid)} > {format_millions(median_price)})")
            return
    
    if percentage <= TARGET_PERCENTAGE:
        tracking_queue.put(f"Pass: {auction['item_name']} - Low percentage ({percentage:.2f}%)")
        return
    if profits <= MIN_PROFITS:
        tracking_queue.put(f"Pass: {auction['item_name']} - Insufficient profits ({format_millions(profits)})")
        return
    if volume <= MIN_VOLUME:
        tracking_queue.put(f"Pass: {auction['item_name']} - Low volume ({volume})")
        return
    
    auction_info = [
        auction['item_name'],
        auction['uuid'],
        format_time(auction['start']),
        datetime.now().strftime('%H:%M:%S'),
        f"{starting_bid:,}",
        f"{lowest_bin:,}",
        f"{data['fastSell']:,}",
        f"{median_price:,}",
        f"{volume:,}",
        f"{percentage:.2f}%, {format_millions(profits)}"
    ]
    
    queue.put(auction_info)
    tracking_queue.put(f"Accepted: {auction['uuid']}")
    winsound.Beep(1000, 500)

async def display_auctions(session, queue, tracking_queue):
    global TOTAL_CHECKED
    auctions = await fetch_auctions(session)
    sorted_auctions = sorted(auctions, key=lambda x: x['start'], reverse=True)
    
    current_time = int(time.time() * 1000)
    filtered_auctions = [
        auction for auction in sorted_auctions
        if auction['start'] + 60000 > current_time
        and auction.get('bin') and auction['uuid'] not in previous_auctions
    ]
    TOTAL_CHECKED += len(filtered_auctions)
    batch_size = 50
    for i in range(0, len(filtered_auctions), batch_size):
        batch = filtered_auctions[i:i + batch_size]
        tasks = [check_auction(session, auction, queue, tracking_queue) for auction in batch]
        await asyncio.gather(*tasks)
    app.update_speed_label()

async def fetch_and_display_auctions(queue, tracking_queue):
    async with aiohttp.ClientSession() as session:
        while True:
            await display_auctions(session, queue, tracking_queue)

class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hypixel Auction Tools (Created by Mingon)")
        self.geometry("1400x640")
        self.create_treeview()
        self.default_font = ('Helvetica', 11)
        self.option_add("*Font", self.default_font)
        self.queue = Queue()
        self.tracking_queue = Queue()
        self.count = 1
        self.create_bottom_frame()
        self.create_input_widgets()
        self.create_tracking_text()
        self.after(100, self.check_queue)
        self.after(100, self.check_tracking_queue)
        self.bind_all('<Control-c>', self.handle_ctrl_c)
        self.reset_previous_auctions()
        self.start_async_loop()

    def create_treeview(self):
        columns = ("No", "item_name", "uuid", "start_time", "display_time", "starting_bid", "lowest_bin", "fast_sell", "median_price", "volume", "profits")
        self.tree = ttk.Treeview(self, columns=columns, height=15, show='headings')
        self.tree.pack(padx=10, pady=10, expand=True, fill=tk.BOTH)
        for col in columns:
            self.tree.heading(col, text=col.replace('_', ' ').title())
        total_width = 1400
        col_widths = self.calculate_column_widths(total_width, len(columns))
        for col, width in col_widths.items():
            self.tree.column(col, width=width)
        
        self.tree.bind("<Motion>", self.on_treeview_hover)

    def on_treeview_hover(self, event):
        self.tree.config(cursor="hand2")

    def calculate_column_widths(self, total_width, num_columns):
        col_widths = {}
        col1_width = int(total_width * 0.02)
        col2_width = int(total_width * 0.2)
        remaining_width = total_width - col1_width - col2_width
        other_col_width = int(remaining_width / (num_columns - 3) - 50)
        for col in ["No", "item_name", "uuid", "start_time", "display_time", "starting_bid", "lowest_bin", "fast_sell", "median_price", "volume", "profits"]:
            if col == "No" or col == "volume":
                col_widths[col] = col1_width
            elif col == "item_name":
                col_widths[col] = col2_width
            else:
                col_widths[col] = other_col_width
        return col_widths

    def create_bottom_frame(self):
        self.bottom_frame = tk.Frame(self, bg="#f5f5f5")
        self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=10)
        self.tracking_frame = tk.Frame(self.bottom_frame, bg="#e0e0e0")
        self.tracking_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5, pady=5)
        self.soon_frame = tk.Frame(self.bottom_frame, bg="#dcdcdc")
        self.soon_frame.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH, padx=5, pady=5)

    def create_input_widgets(self):
        tk.Label(self.soon_frame, text="Min % Profits:", bg="#dcdcdc").grid(row=0, column=0, padx=10, pady=10)
        self.target_percentage_entry = tk.Entry(self.soon_frame, bg="white")
        self.target_percentage_entry.grid(row=0, column=1, padx=5, pady=5)
        self.target_percentage_entry.insert(0, str(TARGET_PERCENTAGE))
        self.speed_label = tk.Label(self.soon_frame, text="Checked: 0 Auctions", font=('Helvetica', 10))
        self.speed_label.grid(row=0, column=2, padx=5, pady=5, sticky='w')
        tk.Label(self.soon_frame, text="Profit Base:").grid(row=1, column=0, padx=5, pady=5)
        self.profit_base_var = tk.StringVar(value=PROFIT_BASE)
        tk.Radiobutton(self.soon_frame, text="Lowest Bin", variable=self.profit_base_var, value='lowest_bin').grid(row=1, column=1, sticky='w')
        tk.Radiobutton(self.soon_frame, text="Median Price", variable=self.profit_base_var, value='median_price').grid(row=1, column=2, sticky='w')
        tk.Label(self.soon_frame, text="Min Profits:").grid(row=2, column=0, padx=5, pady=5)
        self.min_profits_entry = tk.Entry(self.soon_frame)
        self.min_profits_entry.grid(row=2, column=1, padx=5, pady=5)
        self.min_profits_entry.insert(0, str(MIN_PROFITS))
        tk.Label(self.soon_frame, text="Min Volume:").grid(row=3, column=0, padx=5, pady=5)
        self.min_volume_entry = tk.Entry(self.soon_frame)
        self.min_volume_entry.grid(row=3, column=1, padx=5, pady=5)
        self.min_volume_entry.insert(0, str(MIN_VOLUME))
        update_button = tk.Button(self.soon_frame, text="Update Values", command=self.update_values)
        update_button.grid(row=4, column=0, columnspan=2, padx=5, pady=5)
        clear_button = tk.Button(self.soon_frame, text="Clear", command=self.clear_tables)
        clear_button.grid(row=4, column=1, columnspan=2, padx=5, pady=5)

    def create_tracking_text(self):
        # Tạo khung để chứa ô tìm kiếm và nút tìm kiếm
        search_frame = tk.Frame(self.tracking_frame, bg="lightgrey")
        search_frame.pack(fill=tk.X, padx=5, pady=5)

        # Thêm ô tìm kiếm
        tk.Label(search_frame, bg="lightgrey").pack(side=tk.LEFT)
        self.search_entry = tk.Entry(search_frame, width=50)
        self.search_entry.pack(side=tk.LEFT)
        
        # Thêm nút tìm kiếm
        search_button = tk.Button(search_frame, text="Search", command=self.search_tracking_text, font=('Helvetica', 9))
        search_button.pack(side=tk.LEFT, padx=10)

        # Thêm phần hiển thị kết quả
        self.tracking_text = tk.Text(self.tracking_frame, height=10, bg="lightgrey", wrap=tk.WORD)
        self.tracking_text.tag_configure("accepted", foreground="darkgreen")
        self.tracking_text.tag_configure("pass", foreground="red")
        self.tracking_text.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)

    def search_tracking_text(self):
        search_term = self.search_entry.get().strip()
        if not search_term:
            return

        # Xoá các đánh dấu tìm kiếm cũ
        self.tracking_text.tag_remove("highlight", '1.0', tk.END)
        
        # Chuyển đổi từ khóa tìm kiếm thành chữ thường
        search_term = search_term.lower()

        # Tìm kiếm và đánh dấu kết quả
        start = '1.0'
        first_result = None
        while True:
            start = self.tracking_text.search(search_term, start, stopindex=tk.END, nocase=True)
            if not start:
                break
            end = f"{start}+{len(search_term)}c"
            self.tracking_text.tag_add("highlight", start, end)
            self.tracking_text.tag_configure("highlight", background="yellow", foreground="red")  # Đổi màu chữ và nền
            if not first_result:
                first_result = start
            start = end
        
        if first_result:
            self.tracking_text.mark_set("insert", first_result)
            self.tracking_text.see("insert")
            self.tracking_text.focus_set()

    def update_speed_label(self):
        global TOTAL_CHECKED
        self.speed_label.config(text=f"Checked: {TOTAL_CHECKED} auctions")

    def update_values(self):
        global TARGET_PERCENTAGE, MIN_PROFITS, MIN_VOLUME, PROFIT_BASE
        try:
            TARGET_PERCENTAGE = float(self.target_percentage_entry.get())
            MIN_PROFITS = float(self.min_profits_entry.get())
            MIN_VOLUME = float(self.min_volume_entry.get())
            PROFIT_BASE = self.profit_base_var.get()
            tk.messagebox.showinfo("Updated", "Values updated successfully.")
        except ValueError:
            tk.messagebox.showerror("Invalid Input", "Please enter valid numbers.")

    def clear_tables(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def reset_previous_auctions(self):
        global previous_auctions
        previous_auctions.clear()
        self.tracking_text.delete(1.0, tk.END)
        self.after(300000, self.reset_previous_auctions)

    def check_queue(self):
        try:
            while not self.queue.empty():
                auction_info = self.queue.get_nowait()
                auction_info_with_number = [self.count] + auction_info
                self.tree.insert('', tk.END, values=auction_info_with_number)
                self.count += 1
                self.tree.yview_moveto(1)
        except Empty:
            pass
        finally:
            self.after(100, self.check_queue)

    def check_tracking_queue(self):
        try:
            while not self.tracking_queue.empty():
                tracking_info = self.tracking_queue.get_nowait()
                if "Accepted" in tracking_info:
                    self.tracking_text.insert(tk.END, tracking_info + "\n", "accepted")
                else:
                    self.tracking_text.insert(tk.END, tracking_info + "\n", "pass")
                self.tracking_text.see(tk.END)
        except Empty:
            pass
        finally:
            self.after(100, self.check_tracking_queue)

    def handle_ctrl_c(self, event):
        # Check if Treeview has focus
        widget = self.focus_get()
        if isinstance(widget, ttk.Treeview):
            # Xử lý sao chép UUID từ Treeview
            selected_item = widget.selection()
            if selected_item:
                item = widget.item(selected_item)
                values = item['values']
                uuid = values[2]  # Điều chỉnh chỉ mục nếu UUID không ở chỉ mục 2
                formatted_uuid = f"/viewauction {uuid}"
                self.clipboard_clear()
                self.clipboard_append(formatted_uuid)
        elif isinstance(widget, tk.Text) and widget.tag_ranges("sel"):
            # Xử lý sao chép văn bản từ widget Text
            try:
                selected_text = widget.get("sel.first", "sel.last")
                self.clipboard_clear()
                self.clipboard_append(selected_text)
            except tk.TclError:
                tk.messagebox.showwarning("Selection Error", "Failed to copy selected text.")

    def start_async_loop(self):
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=self.run_async_loop, args=(loop,), daemon=True)
        t.start()

    def run_async_loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_until_complete(fetch_and_display_auctions(self.queue, self.tracking_queue))

if __name__ == "__main__":
    app = Application()
    app.iconbitmap('icon.ico')
    app.mainloop()