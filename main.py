#!/usr/bin/env python3
import asyncio
import re
import threading
from pathlib import Path
from telethon import TelegramClient, errors
from textual.app import App, ComposeResult
from textual import events
from textual.message import Message
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, Button, Input, RichLog, Static, ProgressBar

# Configuration Constants
MAX_LOG_LINES = 150
LOG_HEIGHT = 12
MAX_BURST = 50
COOLDOWN = 2.0
TURBO_DELAY = 0.05

class ProgressUpdate(Message):
    def __init__(self, count: int):
        super().__init__()
        self.count = count

class AuthDialog(ModalScreen):
    def __init__(self, phone: str, is_2fa: bool = False):
        super().__init__()
        self.phone = phone
        self.is_2fa = is_2fa
        self.input_value = asyncio.Future()

    def compose(self) -> ComposeResult:
        with Vertical(id="auth-container"):
            yield Static(
                f"🔐 Enter {'2FA Password' if self.is_2fa else 'SMS Code'} "
                f"for {self.phone[-4:]}:"
            )
            yield Input(
                placeholder="Enter code/password..." + 
                (" (numbers only)" if not self.is_2fa else ""), 
                id="auth-input"
            )
            with Horizontal():
                yield Button("Submit", id="submit-btn", variant="primary")
                if not self.is_2fa:
                    yield Button("📞 Call Me", id="call-btn", variant="warning")

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "submit-btn":
            self.input_value.set_result(self.query_one("#auth-input", Input).value)
        elif event.button.id == "call-btn":
            self.input_value.set_result("call")
        self.dismiss()

class TelegramSpammer(App):
    TITLE = "Telegram Messenger v9.1"
    SUB_TITLE = "Final Working Edition"
    CSS = f"""
    Screen {{
        background: $surface;
    }}
    #main-container {{
        height: 100%;
        layout: grid;
        grid-rows: auto auto 1fr;
        grid-gutter: 1;
        padding: 1;
    }}
    #control-panel {{
        height: auto;
        border: tall $accent;
        padding: 1;
        background: $panel;
    }}
    #progress-bar {{
        width: 100%;
        height: 3;
        color: $success;
    }}
    #config-panel {{
        padding: 1;
        border: round $accent;
    }}
    #event-log {{
        height: {LOG_HEIGHT};
        overflow-y: auto;
        padding: 1;
        border: round $accent;
    }}
    """

    def __init__(self):
        super().__init__()
        self._init_state()

    def _init_state(self):
        self.active = False
        self.max_speed = False
        self.burst_counter = 0
        self.sent_messages = 0
        self.max_messages = 100
        self.accounts = []
        self.counter_lock = threading.Lock()
        self.clients = []

    def compose(self) -> ComposeResult:
        try:
            yield Header(show_clock=True)
            with Vertical(id="main-container"):
                with Horizontal(id="control-panel"):
                    yield Button("▶ Start", id="start-btn", variant="success")
                    yield Button("⏹ Stop", id="stop-btn", variant="error")
                    yield Button("🚀 Turbo", id="speed-btn", variant="warning")
                    yield Button("🧹 Logs", id="clear-btn", variant="primary")
                yield ProgressBar(total=100, id="progress-bar")
                with Vertical(id="config-panel"):
                    yield Input(placeholder="Target", id="target-input")
                    yield Input(placeholder="Message", id="message-input")
                    yield Input(placeholder="Limit", id="limit-input", value="500")
                    yield Input(placeholder="Delay", id="delay-input", value="0.1")
                yield RichLog(id="event-log", markup=True, wrap=False)
            yield Footer()
        except Exception as e:
            print(f"UI ERROR: {str(e)}")
            raise

    async def on_mount(self) -> None:
        try:
            self.accounts = self.load_accounts()
            if not self.accounts:
                print("ERROR: Add accounts to accounts.txt")
                print("Format: API_ID,API_HASH,+PHONE_NUMBER")
                self.exit()
                return
            
            self.log_event(f"📂 Loaded {len(self.accounts)} accounts")
        except Exception as e:
            print(f"FATAL ERROR: {str(e)}")
            self.exit()

    def load_accounts(self) -> list:
        accounts = []
        try:
            with open("accounts.txt", "r") as f:
                for line in f:
                    parts = line.strip().split(',')
                    if len(parts) >= 3 and re.match(r"^\+\d{8,15}$", parts[2]):
                        accounts.append({
                            "api_id": int(parts[0]),
                            "api_hash": parts[1],
                            "phone": parts[2]
                        })
            return accounts
        except Exception as e:
            print(f"ACCOUNT ERROR: {str(e)}")
            return []

    def log_event(self, message: str):
        try:
            log = self.query_one("#event-log", RichLog)
            lines = log.lines.copy()[-MAX_LOG_LINES:]
            lines.append(message)
            log.clear()
            log.write("\n".join(lines))
            log.scroll_end()
        except:
            print(f"LOG: {message}")

    async def start_flood(self):
        target = self.query_one("#target-input", Input).value.strip()
        message = self.query_one("#message-input", Input).value.strip()
        
        if not target or not message:
            self.log_event("[red]✗ Target/message required![/red]")
            return
            
        self.active = True
        with self.counter_lock:
            self.sent_messages = 0
            self.burst_counter = 0
        
        self.query_one("#progress-bar", ProgressBar).update(
            total=self.max_messages, 
            progress=0
        )
        
        workers = [self.message_worker(acc, target, message) for acc in self.accounts]
        await asyncio.gather(*workers, return_exceptions=True)

    async def message_worker(self, account, target, message):
        client = TelegramClient(
            session=f"sessions/{account['phone']}",
            api_id=account["api_id"],
            api_hash=account["api_hash"]
        )
        
        try:
            await client.connect()
            self.log_event(f"[yellow]⌛ {account['phone'][-4:]} Connecting...[/yellow]")
            
            if not await client.is_user_authorized():
                self.log_event(f"[yellow]🔑 {account['phone'][-4:]} Authenticating...[/yellow]")
                await self.handle_authentication(client, account["phone"])
            
            try:
                entity = await client.get_entity(target)
                self.log_event(f"[green]✅ {account['phone'][-4:]} Ready[/green]")
            except Exception as e:
                self.log_event(f"[red]✗ {account['phone'][-4:]} Target error: {str(e)}[/red]")
                return

            while self.active and self.sent_messages < self.max_messages:
                try:
                    await self.send_message(client, entity, message, account)
                except errors.FloodWaitError as e:
                    await self.handle_flood_wait(e)
                except Exception as e:
                    self.log_event(f"[red]✗ {account['phone'][-4:]} Error: {str(e)}[/red]")
                    break
        except Exception as e:
            self.log_event(f"[red]⚠ {account['phone'][-4:]} Crash: {str(e)}[/red]")
        finally:
            if client.is_connected():
                await client.disconnect()

    async def send_message(self, client, entity, message, account):
        delay = TURBO_DELAY if self.max_speed else float(
            self.query_one("#delay-input", Input).value
        )
        
        if self.burst_counter >= MAX_BURST:
            delay = COOLDOWN
            self.burst_counter = 0
            self.log_event("[yellow]⏳ Cooldown activated[/yellow]")

        await client.send_message(entity, message)
        
        with self.counter_lock:
            self.sent_messages += 1
            self.burst_counter += 1

        self.post_message(ProgressUpdate(self.sent_messages))
        self.log_event(
            f"[{'yellow' if self.max_speed else 'green'}]" +
            f"✓ {account['phone'][-4:]} » " +
            f"({self.sent_messages}/{self.max_messages})[/]"
        )
        
        await asyncio.sleep(delay)

    async def handle_flood_wait(self, e: errors.FloodWaitError):
        wait_time = e.seconds + 5
        self.log_event(f"[red]⏳ Flood wait {wait_time}s[/red]")
        await asyncio.sleep(wait_time)
        with self.counter_lock:
            self.burst_counter = 0

    async def handle_authentication(self, client, phone):
        try:
            session_path = Path(f"sessions/{phone}")
            if session_path.exists():
                session_path.unlink()

            await client.send_code_request(phone)
            code = await self.get_verification_code(phone)

            if code == "call":
                await client.send_code_request(phone, force_sms=False)
                code = await self.get_verification_code(phone, is_retry=True)

            await client.sign_in(phone, code.strip())
            
            if not await client.is_user_authorized():
                password = await self.get_verification_code(phone, is_2fa=True)
                await client.sign_in(password=password.strip())

        except errors.SessionPasswordNeededError:
            password = await self.get_verification_code(phone, is_2fa=True)
            await client.sign_in(password=password.strip())
        except Exception as e:
            self.log_event(f"[red]✗ Auth failed: {str(e)}[/red]")
            raise

    async def get_verification_code(self, phone: str, is_2fa: bool = False, is_retry: bool = False) -> str:
        attempt = 0
        while attempt < 3:
            try:
                dialog = AuthDialog(phone, is_2fa)
                await self.push_screen(dialog)
                code = await dialog.input_value
                
                if is_2fa:
                    if not code or len(code) < 5:
                        raise ValueError("Invalid 2FA password")
                else:
                    if not code.isdigit():
                        raise ValueError("Code must be numeric")
                return code
            except Exception as e:
                attempt += 1
                self.log_event(f"[yellow]⚠ Attempt {attempt}/3: {str(e)}[/yellow]")
                await asyncio.sleep(1)
        
        raise ValueError("Too many failed attempts")

    def on_progress_update(self, event: ProgressUpdate) -> None:
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.update(progress=event.count)
        progress_bar.refresh(layout=True, repaint=True)

    async def toggle_max_speed(self):
        self.max_speed = not self.max_speed
        speed_btn = self.query_one("#speed-btn", Button)
        speed_btn.label = "🐢 Normal" if self.max_speed else "🚀 Turbo"
        speed_btn.variant = "success" if self.max_speed else "warning"
        self.log_event(f"[{'yellow' if self.max_speed else 'green'}]Mode: {'TURBO' if self.max_speed else 'NORMAL'}[/]")

    async def clear_log(self):
        log = self.query_one("#event-log", RichLog)
        log.clear()

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "clear-btn":
            await self.clear_log()
        elif event.button.id == "start-btn":
            asyncio.create_task(self.start_flood())
        elif event.button.id == "stop-btn":
            self.active = False
        elif event.button.id == "speed-btn":
            await self.toggle_max_speed()

if __name__ == "__main__":
    try:
        Path("sessions").mkdir(exist_ok=True)
        TelegramSpammer().run()
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
    except KeyboardInterrupt:
        print("\nOperation cancelled")
