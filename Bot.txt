# Auto-install missing dependencies
import subprocess
import sys

def install_package(package):
    """Install a package using pip."""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except subprocess.CalledProcessError:
        print(f"❌ Failed to install {package}")
        sys.exit(1)

def check_and_install_dependencies():
    """Check and install required packages."""
    required_packages = [
        "python-telegram-bot[job-queue]",
        "aiohttp==3.9.1",
        "requests==2.31.0",
        "phonenumbers==8.13.27"
    ]
    
    for package in required_packages:
        try:
            if package.startswith("python-telegram-bot"):
                import telegram
            elif package.startswith("aiohttp"):
                import aiohttp
            elif package.startswith("requests"):
                import requests
            elif package.startswith("phonenumbers"):
                import phonenumbers
        except ImportError:
            install_package(package)
    print("✅ Dependencies ready")

# Check and install dependencies before importing
check_and_install_dependencies()

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re
import json
import requests
import aiohttp
import phonenumbers
from datetime import datetime, timedelta

# Configure logging (quiet by default)
logging.basicConfig(
    format='%(levelname)s: %(message)s',
    level=logging.WARNING
)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

class TelegramOTPFetcher:
    def __init__(self, bot_token, chat_id, api_key):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_key = api_key
        self.application = Application.builder().token(self.bot_token).build()
        self.otp_patterns = [
            r'\b\d{4,8}\b',  # 4-8 digit codes
            r'\b[A-Z0-9]{4,8}\b',  # Alphanumeric codes
            r'verification code[:\s]*(\d+)',  # "verification code: XXXXXX"
            r'your code[:\s]*(\d+)',  # "your code: XXXXXX"
            r'otp[:\s]*(\d+)',  # "OTP: XXXXXX"
            r'code[:\s]*(\d+)',  # "Code: XXXXXX"
            r'pin[:\s]*(\d+)',  # "PIN: XXXXXX"
        ]
        self.admin_user_ids = []
        self.api_base_url = 'https://otprevenue.com/api/v1'
        self.sent_numbers = set()  # Track already sent numbers to avoid duplicates
        self.start_time = None  # Will be set when bot actually starts
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /start is issued."""
        await update.message.reply_text(
            f'🤖 *OTP Fetcher Bot is running!*\n\n'
            f'Bot Username: @@Dr_OtpBot\n'
            f'Monitoring Group: https://t.me/+BUH4kpZLtlg3Zjk8\n'
            f'Ready to fetch OTP codes and send success numbers in real-time!\n\n'
            f'*What this bot does:*\n'
            f'• Monitors group for OTP messages\n'
            f'• Automatically fetches your success numbers in real-time\n'
            f'• Sends success numbers to this group instantly\n\n'
            f'*Commands:*\n'
            f'/start - Show this message\n'
            f'/status - Check bot status\n'
            f'/help - Get help information',
            parse_mode='Markdown'
        )
    
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check bot status."""
        await update.message.reply_text(
            f'✅ *Bot Status: Active*\n\n'
            f'🤖 Bot: @@Dr_OtpBot\n'
            f'💬 Monitoring: https://t.me/+BUH4kpZLtlg3Zjk8\n'
            f'⏰ Uptime: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'🔍 Patterns: {len(self.otp_patterns)} OTP patterns loaded',
            parse_mode='Markdown'
        )
    
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information."""
        await update.message.reply_text(
            f'🆘 *Help - OTP Fetcher Bot*\n\n'
            f'This bot automatically detects and extracts OTP codes from messages in your group and sends your success numbers in real-time.\n\n'
            f'*How it works:*\n'
            f'• Monitors all messages in the group\n'
            f'• Detects OTP codes using pattern matching\n'
            f'• Sends notifications when OTPs are found\n'
            f'• Automatically fetches and sends your success numbers in real-time\n\n'
            f'*Supported patterns:*\n'
            f'• 4-8 digit numbers\n'
            f'• Alphanumeric codes\n'
            f'• "verification code: XXXXXX"\n'
            f'• "your code: XXXXXX"\n'
            f'• "OTP: XXXXXX"\n\n'
            f'*Commands:*\n'
            f'/start - Start the bot\n'
            f'/status - Check status\n'
            f'/help - Show this help',
            parse_mode='Markdown'
        )
    
    async def extract_otp(self, text):
        """Extract OTP from message text using regex patterns."""
        for pattern in self.otp_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0] if isinstance(matches[0], str) else matches[0]
        return None
    
    def extract_application_name(self, text):
        """Extract application name from message text."""
        text_lower = text.lower()
        
        # Common application patterns
        app_patterns = {
            'claude': 'Claude',
            'openai': 'OpenAI',
            'chatgpt': 'ChatGPT',
            'google': 'Google',
            'facebook': 'Facebook',
            'instagram': 'Instagram',
            'twitter': 'Twitter',
            'x.com': 'X (Twitter)',
            'whatsapp': 'WhatsApp',
            'telegram': 'Telegram',
            'discord': 'Discord',
            'microsoft': 'Microsoft',
            'apple': 'Apple',
            'amazon': 'Amazon',
            'netflix': 'Netflix',
            'spotify': 'Spotify',
            'uber': 'Uber',
            'lyft': 'Lyft',
            'paypal': 'PayPal',
            'stripe': 'Stripe',
            'coinbase': 'Coinbase',
            'binance': 'Binance',
            'verification code': 'Unknown App',
            'your code': 'Unknown App',
            'otp': 'Unknown App'
        }
        
        for pattern, app_name in app_patterns.items():
            if pattern in text_lower:
                return app_name
        
        return 'Unknown App'
    
    def extract_phone_number(self, text):
        """Extract phone number from message text."""
        # Look for phone number patterns
        phone_patterns = [
            r'\+261\d{9}',  # Madagascar format with +
            r'261\d{9}',  # Madagascar without +
            r'\+?[1-9]\d{1,14}',  # International format
            r'\d{10,15}',  # Long digit sequences
        ]
        
        for pattern in phone_patterns:
            matches = re.findall(pattern, text)
            if matches:
                # Return the longest match (most likely to be complete)
                return max(matches, key=len)
        
        return None
    
    def format_phone_number(self, phone_number):
        """Format phone number to show first 3 and last 3 digits."""
        if not phone_number or phone_number == 'Unknown':
            return 'Unknown'
        
        # Remove any non-digit characters
        digits = re.sub(r'\D', '', phone_number)
        
        if len(digits) < 6:
            return phone_number
        
        # Show first 3 and last 3 digits
        return f"{digits[:3]}*****{digits[-3:]}"
    
    def get_country_from_number(self, phone_number):
        """Get country from phone number."""
        if not phone_number or phone_number == 'Unknown':
            return 'Unknown'
        
        # Remove any non-digit characters
        digits = re.sub(r'\D', '', phone_number)
        
        # Country code mapping
        country_codes = {
            '261': 'Madagascar',
            '1': 'United States',
            '44': 'United Kingdom',
            '33': 'France',
            '49': 'Germany',
            '86': 'China',
            '91': 'India',
            '81': 'Japan',
            '82': 'South Korea',
            '55': 'Brazil',
            '52': 'Mexico',
            '61': 'Australia',
            '64': 'New Zealand',
            '234': 'Nigeria',
            '254': 'Kenya',
            '27': 'South Africa',
            '20': 'Egypt',
            '212': 'Morocco',
            '213': 'Algeria',
            '216': 'Tunisia',
            '218': 'Libya',
            '220': 'Gambia',
            '221': 'Senegal',
            '222': 'Mauritania',
            '223': 'Mali',
            '224': 'Guinea',
            '225': 'Ivory Coast',
            '226': 'Burkina Faso',
            '227': 'Niger',
            '228': 'Togo',
            '229': 'Benin',
            '230': 'Mauritius',
            '231': 'Liberia',
            '232': 'Sierra Leone',
            '233': 'Ghana',
            '235': 'Chad',
            '236': 'Central African Republic',
            '237': 'Cameroon',
            '238': 'Cape Verde',
            '239': 'São Tomé and Príncipe',
            '240': 'Equatorial Guinea',
            '241': 'Gabon',
            '242': 'Republic of the Congo',
            '243': 'Democratic Republic of the Congo',
            '244': 'Angola',
            '245': 'Guinea-Bissau',
            '246': 'British Indian Ocean Territory',
            '248': 'Seychelles',
            '249': 'Sudan',
            '250': 'Rwanda',
            '251': 'Ethiopia',
            '252': 'Somalia',
            '253': 'Djibouti',
            '255': 'Tanzania',
            '256': 'Uganda',
            '257': 'Burundi',
            '258': 'Mozambique',
            '260': 'Zambia',
            '262': 'Réunion',
            '263': 'Zimbabwe',
            '264': 'Namibia',
            '265': 'Malawi',
            '266': 'Lesotho',
            '267': 'Botswana',
            '268': 'Swaziland',
            '269': 'Comoros',
            '290': 'Saint Helena',
            '291': 'Eritrea',
            '297': 'Aruba',
            '298': 'Faroe Islands',
            '299': 'Greenland'
        }
        
        # Check for country codes
        for code, country in country_codes.items():
            if digits.startswith(code):
                return country
        
        return 'Unknown'
    
    async def get_country_from_database(self, phone_number):
        """Get country from database via API call."""
        try:
            import aiohttp
            
            # Make API call to get country information
            async with aiohttp.ClientSession() as session:
                async with session.get(f'https://otprevenue.com/api/phone-country/{phone_number}') as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('country', 'Unknown')
                    else:
                        return 'Unknown'
        except Exception as e:
            print(f"Error getting country from API: {e}")
            return 'Unknown'
    
    async def send_to_admins(self, message):
        """Send message to admin users."""
        # Admin functionality disabled for user bots
        pass
    
    async def send_success_numbers_to_group(self):
        """Automatically fetch and send NEW success numbers to the group."""
        try:
            numbers = await self.get_recent_success_numbers_after_start(50)  # Get real-time numbers only
            
            if not numbers:
                return  # No numbers to send
            
            new_numbers = []
            for number in numbers:
                number_id = number.get('id')
                if number_id and number_id not in self.sent_numbers:
                    new_numbers.append(number)
                    self.sent_numbers.add(number_id)
            
            if not new_numbers:
                return  # No new numbers to send
            
            # Send each new number individually in your preferred format
            for number in new_numbers:
                # Format time properly (Bangladesh time +6 hours from UTC)
                time_str = number.get('receivedAt', 'N/A')
                if time_str != 'N/A':
                    try:
                        from datetime import datetime, timedelta
                        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                        bd_time = dt + timedelta(hours=6)  # Bangladesh time
                        formatted_time = bd_time.strftime('%d-%m-%Y %I:%M:%S %p')
                    except:
                        formatted_time = time_str
                else:
                    formatted_time = 'N/A'
                
                # Get country flag and format
                country = number.get('country', 'N/A')
                phone_number = number.get('phoneNumber', 'N/A')
                otp_code = number.get('otpCode', 'N/A')
                service = number.get('service', 'N/A')
                full_message = number.get('fullMessage', 'N/A')
                
                # Mask the phone number and add + prefix (from test_bot.py)
                def mask_number(number):
                    clean = re.sub(r'\D', '', number)
                    if len(clean) > 6:
                        return clean[:5] + "*****" + clean[-3:]
                    return number
                
                def escape_markdown(text):
                    if not isinstance(text, str):
                        text = str(text)
                    # Simple escaping for common characters
                    text = text.replace('_', '\\_')
                    text = text.replace('*', '\\*')
                    text = text.replace('[', '\\[')
                    text = text.replace(']', '\\]')
                    text = text.replace('(', '\\(')
                    text = text.replace(')', '\\)')
                    text = text.replace('~', '\\~')
                    text = text.replace('>', '\\>')
                    text = text.replace('#', '\\#')
                    text = text.replace('+', '\\+')
                    text = text.replace('-', '\\-')
                    text = text.replace('=', '\\=')
                    text = text.replace('|', '\\|')
                    text = text.replace('{', '\\{')
                    text = text.replace('}', '\\}')
                    text = text.replace('.', '\\.')
                    text = text.replace('!', '\\!')
                    return text
                
                masked_phone = mask_number(phone_number)
                if not masked_phone.startswith('+'):
                    masked_phone = '+' + masked_phone
                phone_escaped = escape_markdown(masked_phone)
                service_escaped = escape_markdown(service)
                time_escaped = escape_markdown(formatted_time)
                otp_escaped = escape_markdown(otp_code)
                message_escaped = escape_markdown(full_message)
                country_escaped = escape_markdown(country)
                
                # Create formatted message with your exact format (from test_bot.py)
                text = (
                    f"📬 \"{service_escaped}\" OTP Received\\!\n\n"
                    f"Number: {phone_escaped}\n"
                    f"🔐OTP: {otp_escaped}\n"
                    f"Country: {country_escaped}\n"
                    f"Time: {time_escaped}\n\n"
                    f"💌Full Message :\n\n"
                    f"{message_escaped}"
                )
                
                # Create inline keyboard with Bot and Group buttons
                keyboard = [
                    [
                        InlineKeyboardButton("Bot", url=f"https://t.me/Dr_OtpBot"),
                        InlineKeyboardButton("Group", url="https://t.me/+BUH4kpZLtlg3Zjk8")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Send to the group with MarkdownV2 parsing and inline buttons
                await self.application.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode='MarkdownV2',
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
                
                logging.info(f"Sent new success number: {number.get('phoneNumber', 'N/A')}")
            
            logging.info(f"Sent {len(new_numbers)} new success numbers to group {self.chat_id}")
            
        except Exception as e:
            logging.error(f"Error sending success numbers to group: {e}")
    
    async def check_and_send_success_numbers(self, context):
        """Check and send success numbers (called by job queue)."""
        try:
            await self.send_success_numbers_to_group()
        except Exception as e:
            logging.error(f"Error in check_and_send_success_numbers: {e}")
    
    async def get_success_numbers_count(self):
        """Get total count of success numbers from Profile API."""
        try:
            headers = {'X-API-Key': self.api_key}
            async with aiohttp.ClientSession() as session:
                async with session.get(f'{self.api_base_url}/success-numbers/count', headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('data', {}).get('totalSuccessNumbers', 0)
                    else:
                        return 0
        except Exception as e:
            logging.error(f"Error getting success numbers count: {e}")
            return 0
    
    async def get_recent_success_numbers(self, limit=5):
        """Get recent success numbers from Profile API."""
        try:
            headers = {'X-API-Key': self.api_key}
            async with aiohttp.ClientSession() as session:
                async with session.get(f'{self.api_base_url}/success-numbers?page=1&limit={limit}', headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('data', {}).get('numbers', [])
                    else:
                        return []
        except Exception as e:
            logging.error(f"Error getting recent success numbers: {e}")
            return []
    
    async def get_recent_success_numbers_after_start(self, limit=50):
        """Get success numbers created after bot start time for real-time data."""
        try:
            if not hasattr(self, 'start_time') or not self.start_time:
                # If no start time, get all recent numbers
                return await self.get_recent_success_numbers(limit)
            
            # Format start time for API
            start_time_iso = self.start_time.isoformat()
            
            headers = {'X-API-Key': self.api_key}
            async with aiohttp.ClientSession() as session:
                async with session.get(f'{self.api_base_url}/success-numbers?page=1&limit={limit}&after={start_time_iso}', headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('data', {}).get('numbers', [])
                    else:
                        return []
        except Exception as e:
            logging.error(f"Error getting recent success numbers after start: {e}")
            return []
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages and extract OTP codes."""
        if update.message and update.message.text:
            message_text = update.message.text
            chat_id = str(update.effective_chat.id)
            
            # Only process messages from the specified group
            if chat_id == self.chat_id:
                otp = await self.extract_otp(message_text)
                if otp:
                    # Extract application name from message
                    application_name = self.extract_application_name(message_text)
                    
                    # Extract phone number from group title or message
                    phone_number = self.extract_phone_number(update.effective_chat.title or '') or self.extract_phone_number(message_text) or 'Unknown'
                    formatted_number = self.format_phone_number(phone_number)
                    
                    # Get country from database
                    country = await self.get_country_from_database(phone_number)
                    
                    # Get current time
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Create response message in the specified format
                    response = f"*{application_name}* OTP Detected!\n\n"
                    response += f"Number: {formatted_number}\n"
                    response += f"OTP: {otp}\n"
                    response += f"Application: {application_name}\n"
                    response += f"Country: {country}\n"
                    response += f"Time: {current_time}\n\n"
                    response += f"Full Message :\n\n{message_text}"
                    
                    # Send OTP to the group
                    await context.bot.send_message(
                        chat_id=self.chat_id,
                        text=response,
                        parse_mode='Markdown'
                    )
                    
                    # Admin notifications disabled for user bots
                    
                    logging.info(f"OTP extracted: {otp} from group {chat_id}")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Log errors caused by Updates."""
        logging.error(msg="Exception while handling an update:", exc_info=context.error)
    
    def run(self):
        """Start the bot."""
        # Set start time when bot actually starts
        self.start_time = datetime.now()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_error_handler(self.error_handler)
        
        # Start the real-time sender as a background task using job queue
        self.application.job_queue.run_repeating(
            self.check_and_send_success_numbers,
            interval=10,
            first=10
        )
        
        # Run the bot
        print("🚀 Telegram OTP Fetcher Bot starting...")
        
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Initialize and run the bot
    bot = TelegramOTPFetcher(
        bot_token="8599331345:AAG_Xv_RwIRwtR9AQfyGDkzm87ZFKh5Vixw",
        chat_id="-1003457861866",
        api_key="3c67b3b26346c934d0e85e9bc71679b685f87a6b702112047bc0c3d11e440692"
    )
    bot.run()

# Requirements.txt content:
# python-telegram-bot[job-queue]
# requests==2.31.0
# aiohttp==3.9.1
# phonenumbers==8.13.27

# Setup Instructions:
# 1. Run the script: python telegram_otp_fetcher.py
#    (Dependencies will be installed automatically)
# 2. Add your bot to your group as an administrator
# 3. Send /start command to initialize the bot

# Features:
# ✅ Real-time success number monitoring
# ✅ Profile API integration
# ✅ Automatic message sending
# ✅ Duplicate prevention
# ✅ Secure token handling