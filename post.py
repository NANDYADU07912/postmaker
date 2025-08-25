import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, Chat
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
from telegram.error import TelegramError, Forbidden, BadRequest
import pymongo
from pymongo import MongoClient
import os
import re

# Disable HTTP logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

BOT_TOKEN = "7751847390:AAHnPKzT3pWCfKqsSrSVRDjnvbT_KGTs3YY"
ADMIN_ID = 7574330905
MONGO_URI = "mongodb+srv://pusers:nycreation@nycreation.pd4klp1.mongodb.net/?retryWrites=true&w=majority&appName=NYCREATION"
SUPPORT_CHANNEL = "@ShrutiBots"

client = MongoClient(MONGO_URI)
db = client['telegram_bot']
users_collection = db['users']
posts_collection = db['posts']

# Configure logging to only show errors
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.ERROR
)
logger = logging.getLogger(__name__)

user_states = {}
chat_selection_data = {}

class PostData:
    def __init__(self):
        self.image = None
        self.caption = ""
        self.inline_buttons = []
        self.target_chat = None
        self.step = "start"

class ChatSelectionData:
    def __init__(self):
        self.chats = []
        self.current_page = 0
        self.selected_chat = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    first_name = update.effective_user.first_name or "User"
    
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "username": username,
                    "first_name": first_name,
                    "last_seen": datetime.now(),
                    "is_active": True
                }
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"Database error: {e}")
    
    keyboard = [
        [KeyboardButton("📝 Create Post"), KeyboardButton("📊 Get Chat ID")],
        [KeyboardButton("📢 Broadcast (Admin Only)"), KeyboardButton("ℹ️ Help")],
        [KeyboardButton("🎨 Text Formatter"), KeyboardButton("📞 Support")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    welcome_text = f"🎉 Welcome {first_name}! I'm your advanced Post & Broadcast Bot. Use the buttons below!"
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = "🔧 Bot Commands: /start, /post, /getchatid, /broadcast (Admin), /format, /help"
    await update.message.reply_text(help_text)

async def format_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    format_text = "🎨 Text Formatting: *Bold*, _Italic*, `Code`, [Links](URL)"
    await update.message.reply_text(format_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id == ADMIN_ID and context.user_data.get('waiting_broadcast'):
        await handle_broadcast_message(update, context)
        return
    
    if text == "📝 Create Post":
        await start_post_creation(update, context)
    elif text == "📊 Get Chat ID":
        await get_chat_id_menu(update, context)
    elif text == "📢 Broadcast (Admin Only)":
        if user_id == ADMIN_ID:
            await start_broadcast(update, context)
        else:
            await update.message.reply_text("❌ Only Admin can use this feature!")
    elif text == "ℹ️ Help":
        await help_command(update, context)
    elif text == "🎨 Text Formatter":
        await format_guide(update, context)
    elif text == "📞 Support":
        keyboard = [[InlineKeyboardButton("📱 Join Support Channel", url=f"https://t.me/{SUPPORT_CHANNEL[1:]}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Support: {SUPPORT_CHANNEL}", reply_markup=reply_markup)
    else:
        if user_id in user_states:
            await handle_post_step(update, context)
        else:
            await update.message.reply_text("Please select an option from menu or use /start command.")

async def get_chat_id_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Create a new chat selection session
    chat_selection_data[user_id] = ChatSelectionData()
    
    keyboard = [
        [InlineKeyboardButton("👥 My Groups", callback_data="list_groups")],
        [InlineKeyboardButton("📢 My Channels", callback_data="list_channels")],
        [InlineKeyboardButton("💬 Current Chat", callback_data="current_chat")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_chat_selection")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = "🔍 Select where you want to get Chat ID from:\n\n"
    message_text += "• 👥 My Groups - List all your groups\n"
    message_text += "• 📢 My Channels - List all your channels\n"
    message_text += "• 💬 Current Chat - Get ID of this chat"
    
    await update.message.reply_text(message_text, reply_markup=reply_markup)

async def handle_chat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    await query.answer()
    
    if data == "current_chat":
        chat = query.message.chat
        chat_type = "Group" if chat.type in [Chat.GROUP, Chat.SUPERGROUP] else "Channel" if chat.type == Chat.CHANNEL else "Private Chat"
        
        message_text = f"💬 Current Chat Information:\n\n"
        message_text += f"🆔 Chat ID: `{chat.id}`\n"
        message_text += f"📋 Type: {chat_type}\n"
        
        if hasattr(chat, 'title') and chat.title:
            message_text += f"📛 Title: {chat.title}\n"
        
        if hasattr(chat, 'username') and chat.username:
            message_text += f"👤 Username: @{chat.username}\n"
        
        message_text += f"\n💡 Use this ID in your post targeting."
        
        await query.edit_message_text(message_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    elif data == "list_groups":
        await query.edit_message_text("🔄 Fetching your groups...")
        
        # In a real implementation, you would fetch user's groups from Telegram
        # This is a placeholder implementation
        keyboard = [
            [InlineKeyboardButton("➕ Add Bot to a Group", url="https://t.me/YourBotUsername?startgroup=true")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="list_groups")],
            [InlineKeyboardButton("↩️ Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = "👥 Your Groups:\n\n"
        message_text += "To get a group's ID, make sure:\n"
        message_text += "1. You are an admin in the group\n"
        message_text += "2. The bot is added to the group\n"
        message_text += "3. The bot has admin rights in the group\n\n"
        message_text += "Then use /getchatid command in that group."
        
        await query.edit_message_text(message_text, reply_markup=reply_markup)
        return
    
    elif data == "list_channels":
        await query.edit_message_text("🔄 Fetching your channels...")
        
        # In a real implementation, you would fetch user's channels from Telegram
        # This is a placeholder implementation
        keyboard = [
            [InlineKeyboardButton("➕ Add Bot to a Channel", url="https://t.me/YourBotUsername?startchannel=true")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="list_channels")],
            [InlineKeyboardButton("↩️ Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = "📢 Your Channels:\n\n"
        message_text += "To get a channel's ID, make sure:\n"
        message_text += "1. You are an admin in the channel\n"
        message_text += "2. The bot is added to the channel\n"
        message_text += "3. The bot has admin rights in the channel\n\n"
        message_text += "Then use /getchatid command in that channel."
        
        await query.edit_message_text(message_text, reply_markup=reply_markup)
        return
    
    elif data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("👥 My Groups", callback_data="list_groups")],
            [InlineKeyboardButton("📢 My Channels", callback_data="list_channels")],
            [InlineKeyboardButton("💬 Current Chat", callback_data="current_chat")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_chat_selection")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message_text = "🔍 Select where you want to get Chat ID from:\n\n"
        message_text += "• 👥 My Groups - List all your groups\n"
        message_text += "• 📢 My Channels - List all your channels\n"
        message_text += "• 💬 Current Chat - Get ID of this chat"
        
        await query.edit_message_text(message_text, reply_markup=reply_markup)
        return
    
    elif data == "cancel_chat_selection":
        await query.edit_message_text("❌ Chat selection cancelled.")
        if user_id in chat_selection_data:
            del chat_selection_data[user_id]
        return

async def start_post_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = PostData()
    
    keyboard = [
        [InlineKeyboardButton("📸 Add Image", callback_data="add_image")],
        [InlineKeyboardButton("📝 Skip Image", callback_data="skip_image")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("🎯 Let's create a post! Do you want to add an image?", reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    await query.answer()
    
    # Handle chat selection callbacks first
    if data in ["list_groups", "list_channels", "current_chat", "back_to_main", "cancel_chat_selection"]:
        await handle_chat_selection(update, context)
        return
    
    # Then handle post creation callbacks
    if user_id not in user_states:
        await query.edit_message_text("❌ Session expired. Please restart with /post command.")
        return
    
    post_data = user_states[user_id]
    
    if data == "add_image":
        post_data.step = "waiting_image"
        await query.edit_message_text("📸 Upload Image: Please send your image.")
        
    elif data == "skip_image":
        post_data.step = "waiting_caption"
        await query.edit_message_text("📝 Write Caption: Write your post caption.")
        
    elif data == "add_inline_button":
        post_data.step = "waiting_button"
        await query.edit_message_text("🔘 Add Inline Button: Format: Button Text - Button URL")
        
    elif data == "skip_buttons":
        post_data.step = "waiting_target"
        await query.edit_message_text("🎯 Target Chat: Send Channel/Group username or ID")
        
    elif data == "finish_buttons":
        post_data.step = "waiting_target"
        button_count = len(post_data.inline_buttons)
        await query.edit_message_text(f"✅ {button_count} buttons added! Send target chat.")

async def handle_post_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    post_data = user_states[user_id]
    
    if post_data.step == "waiting_image":
        if update.message.photo:
            post_data.image = update.message.photo[-1].file_id
            post_data.step = "waiting_caption"
            await update.message.reply_text("✅ Image saved! Now write the caption:")
        else:
            await update.message.reply_text("❌ Please send a valid image file.")
            
    elif post_data.step == "waiting_caption":
        post_data.caption = update.message.text
        post_data.step = "waiting_button_choice"
        await update.message.reply_text("✅ Caption saved! Do you want to add inline buttons?")
        
        keyboard = [
            [InlineKeyboardButton("➕ Add Inline Button", callback_data="add_inline_button")],
            [InlineKeyboardButton("⏭️ Skip Buttons", callback_data="skip_buttons")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose an option:", reply_markup=reply_markup)
        
    elif post_data.step == "waiting_button":
        button_text = update.message.text.strip()
        
        if " - " in button_text:
            try:
                text, url = button_text.split(" - ", 1)
                text = text.strip()
                url = url.strip()
                
                if not (url.startswith('http://') or url.startswith('https://') or url.startswith('tg://')):
                    if url.startswith('@') or url.startswith('t.me/'):
                        url = f"https://t.me/{url.lstrip('@').lstrip('t.me/')}"
                    else:
                        url = f"https://{url}"
                
                post_data.inline_buttons.append([InlineKeyboardButton(text, url=url)])
                
                keyboard = [
                    [InlineKeyboardButton("➕ Add More Button", callback_data="add_inline_button")],
                    [InlineKeyboardButton("✅ Finish Buttons", callback_data="finish_buttons")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(f"✅ Button added: {text}", reply_markup=reply_markup)
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {str(e)}")
        else:
            await update.message.reply_text("❌ Invalid format! Use: Button Text - Button URL")
            
    elif post_data.step == "waiting_target":
        target = update.message.text.strip()
        
        if target.lower() == "here":
            target_chat_id = update.effective_chat.id
        elif target.startswith("@"):
            target_chat_id = target
        elif target.lstrip("-").isdigit():
            target_chat_id = int(target)
        else:
            await update.message.reply_text("❌ Invalid chat ID/username format!")
            return
        
        await send_post(update, context, target_chat_id, post_data)

async def send_post(update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id, post_data):
    user_id = update.effective_user.id
    
    try:
        reply_markup = None
        if post_data.inline_buttons:
            reply_markup = InlineKeyboardMarkup(post_data.inline_buttons)
        
        if post_data.image:
            message = await context.bot.send_photo(
                chat_id=target_chat_id,
                photo=post_data.image,
                caption=post_data.caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            message = await context.bot.send_message(
                chat_id=target_chat_id,
                text=post_data.caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        
        try:
            posts_collection.insert_one({
                "user_id": user_id,
                "target_chat_id": str(target_chat_id),
                "message_id": message.message_id,
                "caption": post_data.caption,
                "has_image": bool(post_data.image),
                "inline_buttons_count": len(post_data.inline_buttons),
                "created_at": datetime.now()
            })
        except Exception as e:
            logger.error(f"Database save error: {e}")
        
        success_text = f"✅ Post Successfully Sent! Target: {target_chat_id}, Message ID: {message.message_id}"
        await update.message.reply_text(success_text)
        
    except Forbidden:
        await update.message.reply_text("❌ Permission Error! Bot needs to be admin in target chat.")
    except BadRequest as e:
        error_msg = str(e).lower()
        if "chat not found" in error_msg:
            await update.message.reply_text("❌ Chat not found! Please check the ID/username.")
        elif "not enough rights" in error_msg:
            await update.message.reply_text("❌ Bot doesn't have permission to post in this chat!")
        else:
            await update.message.reply_text(f"❌ Error: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Unexpected error: {str(e)}")
    
    finally:
        if user_id in user_states:
            del user_states[user_id]

async def get_chat_id_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    chat_info = f"🆔 Chat Information:\nCurrent Chat ID: {chat.id}\nYour User ID: {user.id}"
    
    keyboard = [[InlineKeyboardButton("📋 Copy Chat ID", callback_data=f"copy_{chat.id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(chat_info, reply_markup=reply_markup)

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized! Only Admin can use this feature.")
        return
    
    context.user_data['waiting_broadcast'] = True
    await update.message.reply_text("📢 Broadcast Message: Send the message you want to broadcast to all users:")

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID or not context.user_data.get('waiting_broadcast'):
        return
    
    try:
        users = list(users_collection.find({"is_active": True}))
        total_users = len(users)
        
        if total_users == 0:
            await update.message.reply_text("❌ No active users found!")
            return
        
        status_msg = await update.message.reply_text(f"📤 Broadcasting to {total_users} users... Please wait...")
        
        success_count = 0
        failed_count = 0
        blocked_users = []
        
        for i, user in enumerate(users):
            try:
                user_chat_id = user['user_id']
                
                if i % 10 == 0 and i > 0:
                    try:
                        progress_text = f"📤 Broadcasting... Progress: {i}/{total_users}"
                        await status_msg.edit_text(progress_text)
                    except:
                        pass
                
                if update.message.photo:
                    await context.bot.send_photo(
                        chat_id=user_chat_id,
                        photo=update.message.photo[-1].file_id,
                        caption=update.message.caption,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                elif update.message.video:
                    await context.bot.send_video(
                        chat_id=user_chat_id,
                        video=update.message.video.file_id,
                        caption=update.message.caption,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                elif update.message.document:
                    await context.bot.send_document(
                        chat_id=user_chat_id,
                        document=update.message.document.file_id,
                        caption=update.message.caption,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                elif update.message.animation:
                    await context.bot.send_animation(
                        chat_id=user_chat_id,
                        animation=update.message.animation.file_id,
                        caption=update.message.caption,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_chat_id,
                        text=update.message.text,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                
                success_count += 1
                
            except Forbidden:
                users_collection.update_one(
                    {"user_id": user_chat_id},
                    {"$set": {"is_active": False}}
                )
                blocked_users.append(user_chat_id)
                failed_count += 1
            except Exception as e:
                logger.error(f"Broadcast error for user {user_chat_id}: {e}")
                failed_count += 1
            
            await asyncio.sleep(0.05)
        
        completion_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        blocked_note = f"📝 Note: {len(blocked_users)} users were marked as inactive" if blocked_users else "🎉 All active users received the message!"
        
        result_text = f"✅ Broadcast Complete!\nTotal Users: {total_users}\nSuccessfully Sent: {success_count}\nFailed/Blocked: {failed_count}\nCompleted at: {completion_time}\n{blocked_note}"
        
        try:
            await status_msg.edit_text(result_text)
        except:
            await update.message.reply_text(result_text)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Broadcast error: {str(e)}")
    
    finally:
        context.user_data['waiting_broadcast'] = False

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID and context.user_data.get('waiting_broadcast'):
        await handle_broadcast_message(update, context)
        return
    
    if user_id in user_states:
        await handle_post_step(update, context)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID and context.user_data.get('waiting_broadcast'):
        await handle_broadcast_message(update, context)

async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_post_creation(update, context)

async def getchatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await get_chat_id_menu(update, context)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        await start_broadcast(update, context)
    else:
        await update.message.reply_text("❌ Unauthorized! Only Admin can use this feature.")

async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await format_guide(update, context)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Only Admin can view statistics!")
        return
    
    try:
        total_users = users_collection.count_documents({})
        active_users = users_collection.count_documents({"is_active": True})
        inactive_users = total_users - active_users
        
        total_posts = posts_collection.count_documents({})
        posts_with_images = posts_collection.count_documents({"has_image": True})
        posts_with_buttons = posts_collection.count_documents({"inline_buttons_count": {"$gt": 0}})
        
        from datetime import timedelta
        yesterday = datetime.now() - timedelta(days=1)
        recent_users = users_collection.count_documents({"last_seen": {"$gte": yesterday}})
        recent_posts = posts_collection.count_documents({"created_at": {"$gte": yesterday}})
        
        activity_rate = (active_users/total_users)*100 if total_users > 0 else 0
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        stats_text = f"📊 Bot Statistics:\nTotal Users: {total_users}\nActive Users: {active_users}\nInactive Users: {inactive_users}\nActivity Rate: {activity_rate:.1f}%\nTotal Posts: {total_posts}\nPosts with Images: {posts_with_images}\nPosts with Buttons: {posts_with_buttons}\nRecent Active Users (24h): {recent_users}\nNew Posts (24h): {recent_posts}\nGenerated: {current_time}"
        
        await update.message.reply_text(stats_text)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error getting statistics: {str(e)}")

async def handle_inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    await query.answer()
    
    if data.startswith("copy_"):
        chat_id = data.replace("copy_", "")
        await query.answer(f"Chat ID: {chat_id} (Click to copy)", show_alert=True)
        return
    
    # Handle chat selection callbacks
    if data in ["list_groups", "list_channels", "current_chat", "back_to_main", "cancel_chat_selection"]:
        await handle_chat_selection(update, context)
        return
    
    # Handle post creation callbacks
    await handle_callback(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ An error occurred! Please try again or contact support.")
        except:
            pass

def main():
    print("🚀 Starting Enhanced Telegram Bot...")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_error_handler(error_handler)
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("post", post_command))
    application.add_handler(CommandHandler("getchatid", getchatid_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("format", format_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.ALL | filters.ANIMATION | filters.Sticker.ALL, 
        handle_media
    ))
    
    application.add_handler(CallbackQueryHandler(handle_inline_callback))
    
    print("✅ Bot configuration complete!")
    print(f"👨‍💼 Admin ID: {ADMIN_ID}")
    print(f"📱 Support Channel: {SUPPORT_CHANNEL}")
    print("📡 Starting polling...")
    
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Bot error: {e}")

if __name__ == '__main__':
    main()
