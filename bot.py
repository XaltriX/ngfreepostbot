import os
import asyncio
import logging
from datetime import datetime, time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from telegram.error import TelegramError, BadRequest, Forbidden, ChatMigrated
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation
THUMBNAIL, VIDEO_LINK, TITLE, SCHEDULE_TIME, CHANNELS = range(5)

# Store posts data
posts_data = {}
user_channels = {}

# IST timezone
IST = pytz.timezone('Asia/Kolkata')

class TelegramAutoPostBot:
    def __init__(self, token):
        self.token = token
        self.app = Application.builder().token(token).build()
        self.scheduler = AsyncIOScheduler(timezone=IST)
        
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
        
        try:
            if isinstance(update, Update) and update.effective_message:
                error_text = "❌ *An error occurred!*\n\n"
                
                if isinstance(context.error, Forbidden):
                    error_text += "The bot doesn't have permission. Make sure:\n"
                    error_text += "• Bot is added to the channel\n"
                    error_text += "• Bot is an admin\n"
                    error_text += "• Bot has post messages permission"
                elif isinstance(context.error, BadRequest):
                    error_text += "Invalid request. Please check:\n"
                    error_text += "• Channel ID/username is correct\n"
                    error_text += "• Channel exists and is accessible"
                elif isinstance(context.error, ChatMigrated):
                    error_text += "Channel has been migrated. Please add it again."
                else:
                    error_text += "Something went wrong. Please try again."
                
                await update.effective_message.reply_text(error_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in error handler: {e}")
    
    async def verify_bot_admin(self, chat_id, context: ContextTypes.DEFAULT_TYPE):
        """Verify if bot is admin in the channel"""
        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            
            # Check if bot is admin
            if bot_member.status in ['administrator', 'creator']:
                # Check if bot has permission to post
                if bot_member.status == 'creator':
                    return True, None
                
                # For administrators, check specific permissions
                if hasattr(bot_member, 'can_post_messages'):
                    if bot_member.can_post_messages or bot_member.status == 'creator':
                        return True, None
                    else:
                        return False, "Bot doesn't have 'Post Messages' permission"
                else:
                    # For channels, check can_post_messages
                    return True, None
            else:
                return False, f"Bot is not an admin (Status: {bot_member.status})"
                
        except Forbidden:
            return False, "Bot is not a member of this channel"
        except BadRequest as e:
            if "chat not found" in str(e).lower():
                return False, "Channel not found or bot was removed"
            return False, f"Cannot access channel: {str(e)}"
        except Exception as e:
            logger.error(f"Error verifying admin status: {e}")
            return False, f"Error checking permissions: {str(e)}"
    
    async def get_chat_info(self, chat_id, context: ContextTypes.DEFAULT_TYPE):
        """Get channel information"""
        try:
            chat = await context.bot.get_chat(chat_id)
            return chat.title if hasattr(chat, 'title') else str(chat_id), None
        except Exception as e:
            return str(chat_id), str(e)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command - Initialize bot"""
        try:
            user_id = update.effective_user.id
            logger.info(f"User {user_id} started the bot")
            
            welcome_text = """
🌟 *Welcome to Auto-Post Bot!* 🌟

This bot helps you create beautiful posts and schedule them to multiple Telegram channels.

*Commands:*
/newpost - Create a new post
/channels - Manage your channels
/addchannel - Add a channel
/testchannel - Test channel permissions
/cancel - Cancel current operation

*How to add channels:*
1️⃣ Forward any message from your channel
2️⃣ Use /addchannel @username
3️⃣ Use /addchannel -100xxxxxxxxx

⚠️ *Important:* Make sure to add the bot as admin in your channel with 'Post Messages' permission!

Let's get started! Use /newpost to create your first post.
            """
            await update.message.reply_text(welcome_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in start: {e}")
            await update.message.reply_text("❌ Error starting bot. Please try again.")
    
    async def new_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start new post creation"""
        try:
            user_id = update.effective_user.id
            logger.info(f"User {user_id} starting new post")
            
            # Check if user has channels
            if user_id not in user_channels or not user_channels[user_id]:
                await update.message.reply_text(
                    "⚠️ *No channels configured!*\n\n"
                    "Please add at least one channel first:\n"
                    "• Forward a message from your channel\n"
                    "• Use /addchannel @channelname\n"
                    "• Use /addchannel -100xxxxxxxxx",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            
            posts_data[user_id] = {}
            
            await update.message.reply_text(
                "📸 *Step 1: Thumbnail*\n\n"
                "Please send your thumbnail (photo, video, or GIF):",
                parse_mode='Markdown'
            )
            return THUMBNAIL
        except Exception as e:
            logger.error(f"Error in new_post: {e}")
            await update.message.reply_text("❌ Error creating post. Please try /newpost again.")
            return ConversationHandler.END
    
    async def receive_thumbnail(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive thumbnail from user"""
        try:
            user_id = update.effective_user.id
            logger.info(f"User {user_id} sent thumbnail")
            
            if update.message.photo:
                posts_data[user_id]['thumbnail'] = {
                    'type': 'photo',
                    'file_id': update.message.photo[-1].file_id
                }
            elif update.message.video:
                posts_data[user_id]['thumbnail'] = {
                    'type': 'video',
                    'file_id': update.message.video.file_id
                }
            elif update.message.animation:
                posts_data[user_id]['thumbnail'] = {
                    'type': 'animation',
                    'file_id': update.message.animation.file_id
                }
            else:
                await update.message.reply_text("❌ Please send a valid photo, video, or GIF!")
                return THUMBNAIL
            
            await update.message.reply_text(
                "✅ Thumbnail received!\n\n"
                "🔗 *Step 2: Video Link*\n\n"
                "Please send the video link (YouTube, etc.):",
                parse_mode='Markdown'
            )
            return VIDEO_LINK
        except Exception as e:
            logger.error(f"Error in receive_thumbnail: {e}")
            await update.message.reply_text("❌ Error processing thumbnail. Please try again.")
            return THUMBNAIL
    
    async def receive_video_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive video link"""
        try:
            user_id = update.effective_user.id
            link = update.message.text.strip()
            logger.info(f"User {user_id} sent video link: {link}")
            
            # Basic URL validation
            if not (link.startswith('http://') or link.startswith('https://')):
                await update.message.reply_text(
                    "⚠️ Please send a valid URL starting with http:// or https://"
                )
                return VIDEO_LINK
            
            posts_data[user_id]['video_link'] = link
            
            await update.message.reply_text(
                "✅ Video link saved!\n\n"
                "📝 *Step 3: Title*\n\n"
                "Please send the post title:",
                parse_mode='Markdown'
            )
            return TITLE
        except Exception as e:
            logger.error(f"Error in receive_video_link: {e}")
            await update.message.reply_text("❌ Error processing link. Please try again.")
            return VIDEO_LINK
    
    async def receive_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive post title"""
        try:
            user_id = update.effective_user.id
            title = update.message.text.strip()
            logger.info(f"User {user_id} sent title: {title}")
            
            if len(title) > 100:
                await update.message.reply_text("⚠️ Title is too long! Please keep it under 100 characters.")
                return TITLE
            
            posts_data[user_id]['title'] = title
            
            keyboard = [
                [InlineKeyboardButton("📤 Post Now", callback_data='post_now')],
                [InlineKeyboardButton("⏰ Schedule Post", callback_data='schedule_post')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "✅ *Post Ready!*\n\n"
                f"📸 Thumbnail: Uploaded\n"
                f"🔗 Link: {posts_data[user_id]['video_link'][:50]}...\n"
                f"📝 Title: {title}\n\n"
                "What would you like to do?",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return SCHEDULE_TIME
        except Exception as e:
            logger.error(f"Error in receive_title: {e}")
            await update.message.reply_text("❌ Error processing title. Please try again.")
            return TITLE
    
    async def handle_post_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle post now or schedule"""
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = query.from_user.id
            logger.info(f"User {user_id} chose action: {query.data}")
            
            if query.data == 'post_now':
                await query.edit_message_text("📤 *Posting to channels...*", parse_mode='Markdown')
                success, failed = await self.post_to_channels(user_id, context)
                
                result_text = f"✅ *Post Complete!*\n\n"
                result_text += f"✓ Successfully posted to {success} channel(s)\n"
                if failed:
                    result_text += f"✗ Failed: {len(failed)} channel(s)\n\n"
                    result_text += "*Failed Channels:*\n"
                    for channel, reason in failed:
                        result_text += f"• `{channel}`: {reason}\n"
                
                await query.message.reply_text(result_text, parse_mode='Markdown')
                return ConversationHandler.END
            
            elif query.data == 'schedule_post':
                await query.edit_message_text(
                    "⏰ *Schedule Post*\n\n"
                    "Send the time in IST format (HH:MM)\n"
                    "Example: 14:30 for 2:30 PM\n"
                    "Example: 09:00 for 9:00 AM",
                    parse_mode='Markdown'
                )
                return CHANNELS
        except Exception as e:
            logger.error(f"Error in handle_post_action: {e}")
            await query.message.reply_text("❌ Error handling action. Please try again.")
            return ConversationHandler.END
    
    async def receive_schedule_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive schedule time"""
        try:
            user_id = update.effective_user.id
            time_str = update.message.text.strip()
            logger.info(f"User {user_id} scheduling for: {time_str}")
            
            try:
                hour, minute = map(int, time_str.split(':'))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("Invalid time range")
                    
                posts_data[user_id]['schedule_time'] = time(hour, minute)
                
                # Schedule the post
                job_id = f"post_{user_id}_{datetime.now().timestamp()}"
                self.scheduler.add_job(
                    self.post_to_channels,
                    CronTrigger(hour=hour, minute=minute, timezone=IST),
                    args=[user_id, context],
                    id=job_id
                )
                
                await update.message.reply_text(
                    f"✅ *Post Scheduled Successfully!*\n\n"
                    f"⏰ Time: {time_str} IST\n"
                    f"📅 Frequency: Daily\n"
                    f"📢 Channels: {len(user_channels.get(user_id, []))}\n\n"
                    f"Your post will be published every day at this time.",
                    parse_mode='Markdown'
                )
                logger.info(f"Scheduled job {job_id} for user {user_id}")
                
            except ValueError as e:
                await update.message.reply_text(
                    "❌ Invalid time format!\n\n"
                    "Please use HH:MM format:\n"
                    "• 14:30 (2:30 PM)\n"
                    "• 09:00 (9:00 AM)\n"
                    "• 23:45 (11:45 PM)"
                )
                return CHANNELS
            
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in receive_schedule_time: {e}")
            await update.message.reply_text("❌ Error scheduling post. Please try again.")
            return ConversationHandler.END
    
    async def post_to_channels(self, user_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Post to all configured channels"""
        success_count = 0
        failed_channels = []
        
        try:
            post_data = posts_data.get(user_id)
            if not post_data:
                logger.warning(f"No post data found for user {user_id}")
                return 0, [("N/A", "No post data")]
            
            # Get user's channels
            channels = user_channels.get(user_id, [])
            if not channels:
                logger.warning(f"No channels configured for user {user_id}")
                return 0, [("N/A", "No channels configured")]
            
            # Format the post
            caption = self.format_post(post_data)
            thumbnail = post_data['thumbnail']
            
            logger.info(f"Posting to {len(channels)} channels for user {user_id}")
            
            # Send to each channel
            for channel in channels:
                try:
                    # Verify bot is admin first
                    is_admin, error = await self.verify_bot_admin(channel, context)
                    
                    if not is_admin:
                        logger.error(f"Bot is not admin in {channel}: {error}")
                        failed_channels.append((channel, error))
                        continue
                    
                    # Send based on thumbnail type
                    if thumbnail['type'] == 'photo':
                        await context.bot.send_photo(
                            chat_id=channel,
                            photo=thumbnail['file_id'],
                            caption=caption,
                            parse_mode='MarkdownV2'
                        )
                    elif thumbnail['type'] == 'video':
                        await context.bot.send_video(
                            chat_id=channel,
                            video=thumbnail['file_id'],
                            caption=caption,
                            parse_mode='MarkdownV2'
                        )
                    elif thumbnail['type'] == 'animation':
                        await context.bot.send_animation(
                            chat_id=channel,
                            animation=thumbnail['file_id'],
                            caption=caption,
                            parse_mode='MarkdownV2'
                        )
                    
                    success_count += 1
                    logger.info(f"✓ Successfully posted to channel {channel}")
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.5)
                    
                except Forbidden as e:
                    error_msg = "Bot is not admin or was removed"
                    logger.error(f"✗ Forbidden error for {channel}: {e}")
                    failed_channels.append((channel, error_msg))
                    
                except BadRequest as e:
                    error_msg = f"Invalid request: {str(e)}"
                    logger.error(f"✗ Bad request for {channel}: {e}")
                    failed_channels.append((channel, error_msg))
                    
                except Exception as e:
                    error_msg = f"Error: {str(e)[:50]}"
                    logger.error(f"✗ Error posting to {channel}: {e}")
                    failed_channels.append((channel, error_msg))
            
            # Log summary
            logger.info(f"Posted to {success_count}/{len(channels)} channels successfully")
            if failed_channels:
                logger.warning(f"Failed channels: {failed_channels}")
            
            return success_count, failed_channels
            
        except Exception as e:
            logger.error(f"Critical error in post_to_channels: {e}")
            return success_count, failed_channels
    
    def format_post(self, post_data: dict) -> str:
        """Format the post with beautiful structure"""
        try:
            title = post_data.get('title', 'Untitled')
            video_link = post_data.get('video_link', '')
            
            # Escape special markdown characters in user input
            title = self.escape_markdown(title)
            video_link = self.escape_markdown(video_link)
            
            post = f"""
╔══════════════════════╗
   🌟 *{title}* 🌟
╚══════════════════════╝

🔗 *Watch Now:*
{video_link}

━━━━━━━━━━━━━━━━━━━━
📢 Join: @NeonGhost\\_Network
━━━━━━━━━━━━━━━━━━━━
            """
            return post.strip()
        except Exception as e:
            logger.error(f"Error formatting post: {e}")
            return "Error formatting post"
    
    def escape_markdown(self, text: str) -> str:
        """Escape markdown special characters"""
        try:
            # Characters that need escaping in Markdown
            escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
            for char in escape_chars:
                text = text.replace(char, f'\\{char}')
            return text
        except Exception as e:
            logger.error(f"Error escaping markdown: {e}")
            return text
    
    async def manage_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manage channels for posting"""
        try:
            user_id = update.effective_user.id
            channels = user_channels.get(user_id, [])
            
            if channels:
                channels_text = "*Your Channels:*\n\n"
                for i, ch in enumerate(channels, 1):
                    # Get channel info
                    chat_name, error = await self.get_chat_info(ch, context)
                    
                    # Verify admin status
                    is_admin, admin_error = await self.verify_bot_admin(ch, context)
                    
                    status = "✅" if is_admin else "❌"
                    channels_text += f"{i}. {status} `{ch}`\n"
                    channels_text += f"   📢 {chat_name}\n"
                    if not is_admin:
                        channels_text += f"   ⚠️ {admin_error}\n"
                    channels_text += "\n"
            else:
                channels_text = "❌ No channels configured\n\n"
            
            help_text = (
                "\n*How to add channels:*\n"
                "1️⃣ Forward any message from your channel\n"
                "2️⃣ /addchannel @username\n"
                "3️⃣ /addchannel -100xxxxxxxxx\n\n"
                "*Other commands:*\n"
                "/removechannel [id] - Remove a channel\n"
                "/testchannel [id] - Test permissions"
            )
            
            await update.message.reply_text(
                channels_text + help_text,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in manage_channels: {e}")
            await update.message.reply_text("❌ Error loading channels.")
    
    async def handle_channel_forward(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle forwarded messages from channels to auto-add them"""
        try:
            user_id = update.effective_user.id
            
            # Check if message is forwarded from a channel
            if hasattr(update.message, 'forward_origin') and update.message.forward_origin:
                forward_origin = update.message.forward_origin
                
                # Handle different types of forward origins
                if hasattr(forward_origin, 'chat'):
                    channel = forward_origin.chat
                    channel_id = channel.id
                    channel_title = getattr(channel, 'title', 'Unknown Channel')
                    
                    logger.info(f"User {user_id} forwarded from channel {channel_id}")
                    
                    # Verify bot is admin
                    is_admin, error = await self.verify_bot_admin(channel_id, context)
                    
                    if user_id not in user_channels:
                        user_channels[user_id] = []
                    
                    if channel_id not in user_channels[user_id]:
                        user_channels[user_id].append(channel_id)
                        
                        if is_admin:
                            await update.message.reply_text(
                                f"✅ *Channel Added Successfully!*\n\n"
                                f"📢 {channel_title}\n"
                                f"🆔 `{channel_id}`\n"
                                f"✓ Bot has admin permissions\n\n"
                                f"You can now post to this channel!",
                                parse_mode='Markdown'
                            )
                        else:
                            await update.message.reply_text(
                                f"⚠️ *Channel Added with Warning!*\n\n"
                                f"📢 {channel_title}\n"
                                f"🆔 `{channel_id}`\n\n"
                                f"❌ *Problem:* {error}\n\n"
                                f"*Please:*\n"
                                f"1. Add bot to your channel\n"
                                f"2. Make bot an admin\n"
                                f"3. Give 'Post Messages' permission\n"
                                f"4. Use /testchannel `{channel_id}` to verify",
                                parse_mode='Markdown'
                            )
                        logger.info(f"Added channel {channel_id} for user {user_id}")
                    else:
                        await update.message.reply_text(
                            f"⚠️ Channel already exists: {channel_title}\n"
                            f"Admin status: {'✅' if is_admin else '❌'}"
                        )
                else:
                    await update.message.reply_text(
                        "⚠️ Could not extract channel info from forwarded message."
                    )
            else:
                await update.message.reply_text(
                    "⚠️ Please forward a message from the channel you want to add."
                )
        except Exception as e:
            logger.error(f"Error in handle_channel_forward: {e}")
            await update.message.reply_text(
                "❌ Error adding channel from forwarded message.\n"
                f"Error: {str(e)}"
            )
    
    async def add_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a channel by ID or link"""
        try:
            user_id = update.effective_user.id
            
            # Check if it's a forwarded message from a channel
            if hasattr(update.message, 'forward_origin') and update.message.forward_origin:
                await self.handle_channel_forward(update, context)
                return
            
            # Get channel identifier from command args
            if not context.args:
                await update.message.reply_text(
                    "📝 *How to add channels:*\n\n"
                    "1️⃣ Forward any message from the channel to me\n"
                    "2️⃣ Use: `/addchannel @username`\n"
                    "3️⃣ Use: `/addchannel -100xxxxxxxx`\n"
                    "4️⃣ Send channel invite link\n\n"
                    "*Examples:*\n"
                    "`/addchannel @mychannel`\n"
                    "`/addchannel -1001234567890`",
                    parse_mode='Markdown'
                )
                return
            
            channel_input = ' '.join(context.args)
            logger.info(f"User {user_id} adding channel: {channel_input}")
            
            # Parse channel identifier
            channel = None
            if 't.me/' in channel_input or 'telegram.me/' in channel_input:
                # Extract username from link
                channel = '@' + channel_input.split('/')[-1]
            elif channel_input.startswith('-100') or channel_input.lstrip('-').isdigit():
                # Channel ID
                try:
                    channel = int(channel_input)
                except ValueError:
                    await update.message.reply_text("❌ Invalid channel ID format")
                    return
            elif channel_input.startswith('@'):
                channel = channel_input
            else:
                channel = '@' + channel_input
            
            # Verify bot is admin
            is_admin, error = await self.verify_bot_admin(channel, context)
            chat_name, _ = await self.get_chat_info(channel, context)
            
            if user_id not in user_channels:
                user_channels[user_id] = []
            
            if channel not in user_channels[user_id]:
                user_channels[user_id].append(channel)
                
                if is_admin:
                    await update.message.reply_text(
                        f"✅ *Channel Added Successfully!*\n\n"
                        f"📢 {chat_name}\n"
                        f"🆔 `{channel}`\n"
                        f"✓ Bot has admin permissions\n\n"
                        f"Ready to post!",
                        parse_mode='Markdown'
                    )
                    logger.info(f"Successfully added channel {channel} for user {user_id}")
                else:
                    await update.message.reply_text(
                        f"⚠️ *Channel Added with Warning!*\n\n"
                        f"📢 {chat_name}\n"
                        f"🆔 `{channel}`\n\n"
                        f"❌ *Problem:* {error}\n\n"
                        f"*Action Required:*\n"
                        f"1. Go to your channel settings\n"
                        f"2. Add this bot as administrator\n"
                        f"3. Enable 'Post Messages' permission\n"
                        f"4. Use /testchannel `{channel}` to verify\n\n"
                        f"💡 *Tip:* You can also forward a message from the channel to add it automatically.",
                        parse_mode='Markdown'
                    )
                    logger.warning(f"Added channel {channel} but bot is not admin")
            else:
                await update.message.reply_text(
                    f"⚠️ Channel already exists!\n\n"
                    f"📢 {chat_name}\n"
                    f"Status: {'✅ Ready' if is_admin else '❌ No permissions'}"
                )
        
        except Exception as e:
            logger.error(f"Error in add_channel: {e}")
            await update.message.reply_text(
                "❌ *Error adding channel!*\n\n"
                "Please check:\n"
                "• Channel username/ID is correct\n"
                "• Channel exists\n"
                "• Bot has access to the channel\n\n"
                f"Error details: {str(e)[:100]}",
                parse_mode='Markdown'
            )
    
    async def test_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test channel permissions"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "Usage: `/testchannel [channel_id]`\n"
                    "Example: `/testchannel -1001234567890`",
                    parse_mode='Markdown'
                )
                return
            
            channel_input = context.args[0]
            
            # Parse channel ID
            try:
                if channel_input.startswith('-'):
                    channel = int(channel_input)
                else:
                    channel = channel_input
            except:
                channel = channel_input
            
            logger.info(f"Testing channel {channel}")
            
            # Get channel info
            chat_name, error = await self.get_chat_info(channel, context)
            
            # Verify admin status
            is_admin, admin_error = await self.verify_bot_admin(channel, context)
            
            result = f"🔍 *Channel Test Results*\n\n"
            result += f"📢 Name: {chat_name}\n"
            result += f"🆔 ID: `{channel}`\n\n"
            
            if is_admin:
                result += "✅ *Status: Ready to post!*\n"
                result += "• Bot is admin\n"
                result += "• Has post permissions\n"
            else:
                result += "❌ *Status: Cannot post!*\n"
                result += f"• Problem: {admin_error}\n\n"
                result += "*Fix:*\n"
                result += "1. Add bot to channel\n"
                result += "2. Make bot admin\n"
                result += "3. Enable 'Post Messages'\n"
            
            await update.message.reply_text(result, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in test_channel: {e}")
            await update.message.reply_text(
                f"❌ Error testing channel\n\n"
                f"Details: {str(e)}",
                parse_mode='Markdown'
            )
    
    async def remove_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove a channel"""
        try:
            user_id = update.effective_user.id
            
            if not context.args:
                await update.message.reply_text(
                    "📝 *Usage:*\n"
                    "`/removechannel [channel_id]`\n\n"
                    "Use /channels to see your channel IDs",
                    parse_mode='Markdown'
                )
                return
            
            channel_input = context.args[0]
            logger.info(f"User {user_id} removing channel: {channel_input}")
            
            # Try to convert to int if it's a numeric ID
            try:
                if channel_input.startswith('-'):
                    channel = int(channel_input)
                else:
                    channel = channel_input
            except:
                channel = channel_input
            
            if user_id in user_channels and channel in user_channels[user_id]:
                # Get channel name before removing
                chat_name, _ = await self.get_chat_info(channel, context)
                
                user_channels[user_id].remove(channel)
                await update.message.reply_text(
                    f"✅ *Channel Removed!*\n\n"
                    f"📢 {chat_name}\n"
                    f"🆔 `{channel}`",
                    parse_mode='Markdown'
                )
                logger.info(f"Removed channel {channel} for user {user_id}")
            else:
                await update.message.reply_text(
                    f"⚠️ Channel not found in your list\n\n"
                    f"Use /channels to see your channels"
                )
        
        except Exception as e:
            logger.error(f"Error in remove_channel: {e}")
            await update.message.reply_text("❌ Error removing channel.")
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current operation"""
        try:
            user_id = update.effective_user.id
            if user_id in posts_data:
                del posts_data[user_id]
            
            await update.message.reply_text(
                "❌ Operation cancelled.\n\n"
                "Use /newpost to start again."
            )
            logger.info(f"User {user_id} cancelled operation")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in cancel: {e}")
            return ConversationHandler.END
    
    def run(self):
        """Start the bot"""
        try:
            # Conversation handler for post creation
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler('newpost', self.new_post)],
                states={
                    THUMBNAIL: [MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.IMAGE | filters.ANIMATION, self.receive_thumbnail)],
                    VIDEO_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_video_link)],
                    TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_title)],
                    SCHEDULE_TIME: [CallbackQueryHandler(self.handle_post_action)],
                    CHANNELS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_schedule_time)]
                },
                fallbacks=[CommandHandler('cancel', self.cancel)],
                per_message=False
            )
            
            # Add handlers
            self.app.add_handler(CommandHandler('start', self.start))
            self.app.add_handler(conv_handler)
            self.app.add_handler(CommandHandler('channels', self.manage_channels))
            self.app.add_handler(CommandHandler('addchannel', self.add_channel))
            self.app.add_handler(CommandHandler('removechannel', self.remove_channel))
            self.app.add_handler(CommandHandler('testchannel', self.test_channel))
            # Handle forwarded messages
            self.app.add_handler(MessageHandler(filters.FORWARDED, self.handle_channel_forward))
            
            # Add error handler
            self.app.add_error_handler(self.error_handler)
            
            # Start scheduler
            self.scheduler.start()
            
            # Start bot
            logger.info("=" * 50)
            logger.info("🤖 Bot is running...")
            logger.info("✅ All systems operational")
            logger.info("📡 Listening for updates...")
            logger.info("=" * 50)
            
            self.app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Critical error starting bot: {e}", exc_info=True)


if __name__ == '__main__':
    # Your bot token
    BOT_TOKEN = '7205909672:AAFgxzF0gZ--jqWjGdMt2v_GF3UxUmFlvkM'
    
    try:
        logger.info("Starting Telegram Auto-Post Bot...")
        bot = TelegramAutoPostBot(BOT_TOKEN)
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)




















