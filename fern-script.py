import discord
import os
import pytz
import dateparser
import asyncio
from discord.ext import tasks
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CHANNEL_ID = 1199581968875139183
private_calendar_id = 'a90d4039983999a9c995d386e278e5f9959db54eb5ba2b6e08bcdf403aba02f1@group.calendar.google.com'

class FernBot(discord.Client):
    def __init__(self, intents, channel_id, calendar_id):
        super().__init__(intents=intents)
        self.channel_id = channel_id
        self.calendar_id = calendar_id
        self.event_creation_sessions = {}
        self.tasks = {}

    async def on_ready(self):
        print(f'We have logged in as {self.user}')
        self.daily_message_task.start()

    def google_calendar_service(self):
        creds = None
        if os.path.exists('E:/fern/token.json'):
            creds = Credentials.from_authorized_user_file('E:/fern/token.json', scopes=['https://www.googleapis.com/auth/calendar'])

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'E:/fern/google-credentials.json', scopes=['https://www.googleapis.com/auth/calendar'])
                creds = flow.run_local_server(port=0)
            with open('E:/fern/token.json', 'w') as token:
                token.write(creds.to_json())
        service = build('calendar', 'v3', credentials=creds)
        return service

    def get_todays_events(self):
        service = self.google_calendar_service()
        
        local_tz = pytz.timezone('America/Toronto')  

        now_local = datetime.now(local_tz)
        
        start_of_day_local = local_tz.localize(datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0))
        end_of_day_local = start_of_day_local + timedelta(days=1)

        start_time_utc = start_of_day_local.astimezone(pytz.utc).isoformat()
        end_time_utc = end_of_day_local.astimezone(pytz.utc).isoformat()

        events_result = service.events().list(
            calendarId=self.calendar_id,
            timeMin=start_time_utc,
            timeMax=end_time_utc,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        events_dict = {}
        for event in events:
            all_day_event = 'date' in event['start']
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))

            if all_day_event:
                end = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=1)).isoformat()

            events_dict[event['summary']] = {
                'start': start,
                'end': end,
                'description': event.get('description', ''),
                'all_day': all_day_event
            }

        return events_dict

    def format_events(self, events_dict):
        if not events_dict:
            return "No events found for today."

        event_messages = []
        for summary, details in events_dict.items():
            if details['all_day']:
                event_message = f"**{summary}** (All day)\nDescription: {details['description']}"
            else:
                start = details['start']
                end = details['end']
                event_message = f"**{summary}**\nStart: {start}\nEnd: {end}\nDescription: {details['description']}"
            event_messages.append(event_message)

        return "\n\n".join(event_messages)
    
    def add_to_calendar(self, summary, description='', start=None, end=None):
        service = self.google_calendar_service()
        event = {
            'summary': summary,
            'description': description,
        }
        if start and end:
            event['start'] = {'dateTime': start, 'timeZone': 'America/Toronto'}  
            event['end'] = {'dateTime': end, 'timeZone': 'America/Toronto'}  
        else:
            today = date.today().isoformat()
            event['start'] = {'date': today}
            event['end'] = {'date': today}

        event = service.events().insert(calendarId=self.calendar_id, body=event).execute()
        return event.get('htmlLink')

    async def on_message(self, message):
        if message.author == self.user or message.author.bot:
            return

        if message.content.lower() == 'fern help':
            help_message = (
                f"{message.author.mention} Here are the commands you can use:\n"
                "- `task [description]`: Add a new task.\n"
                "- `my tasks`: List your tasks with options to delete.\n"
                "- `fern list please`: List today's scheduled events.\n"
                "- `todo [description]`: Add a new event to your calendar.\n"
                "- `remove task [x]`: Remove a [x] task, where x is the task number"
            )
            await message.channel.send(help_message)

        if message.content.lower().startswith('event'):
            todo_item = message.content[5:].strip()
            if todo_item:
                now = datetime.now().replace(microsecond=0, second=0, minute=0) + timedelta(hours=1)
                self.event_creation_sessions[message.author.id] = {
                    'summary': todo_item,
                    'description': '',
                    'start': now,
                    'end': now + timedelta(hours=1),
                    'message_id': None
                }
                embed = self.create_event_embed(self.event_creation_sessions[message.author.id])
                msg = await message.channel.send(embed=embed)
                for emoji in ('⬅️', '➡️', '⬆️', '⬇️', '✅', '❌'):
                    await msg.add_reaction(emoji)
                self.event_creation_sessions[message.author.id]['message_id'] = msg.id
            else:
                await message.channel.send("Please specify an event after 'todo'.")
            return

        elif message.content.lower().startswith('task'):
            task_content = message.content[5:].strip()  
            if task_content:
                user_tasks = self.tasks.get(message.author.id, [])
                user_tasks.append(task_content)
                self.tasks[message.author.id] = user_tasks
                await message.channel.send(f"Task added to your list: `{task_content}`")
            else:
                await message.channel.send("Please specify a task after 'task'.")

        if message.content.lower() == 'fern list please':
            events_dict = self.get_todays_events()
            if events_dict:
                embed = self.create_events_list_embed(events_dict)
                await message.channel.send(embed=embed)
            else:
                await message.channel.send("No events found for today.")
            return
        
        elif message.content.lower() == 'my tasks':
            if message.author.id in self.tasks and self.tasks[message.author.id]:
                embed = await self.create_tasks_embed(message.author.id)
                await message.channel.send(f"{message.author.mention}, here are your tasks:", embed=embed)
            else:
                await message.channel.send(f"{message.author.mention}, you have no tasks.")

        elif message.content.lower().startswith('remove task'):
            try:
                task_number = int(message.content.split(' ')[2]) - 1
                if message.author.id in self.tasks and 0 <= task_number < len(self.tasks[message.author.id]):
                    removed_task = self.tasks[message.author.id].pop(task_number)
                    await message.channel.send(f"Task removed: `{removed_task}`")
                else:
                    await message.channel.send("Invalid task number.")
            except (IndexError, ValueError):
                await message.channel.send("Please specify the task number to remove, e.g., 'remove task 2'.")

    async def create_tasks_embed(self, user_id, highlight_index=None):
        try:
            user = await self.fetch_user(user_id)
            user_name = user.display_name if user else "User"
        except discord.NotFound:
            user_name = "User"

        embed = discord.Embed(title=f"{user_name}'s Task List", description="You really need to get this stuff done...", color=0x00ff00)
        user_tasks = self.tasks.get(user_id, [])
        
        for idx, task in enumerate(user_tasks):
            if highlight_index is not None and idx == highlight_index:
                task_display = f"> {task} <"
            else:
                task_display = task
            embed.add_field(name=f":lotus: Task {idx + 1}", value=task_display, inline=False)
        return embed

    async def on_reaction_add(self, reaction, user):
        if user == self.user or user.bot:
            return

        session = self.event_creation_sessions.get(user.id)
        if session:
            if str(reaction.emoji) in ('⬅️', '➡️', '✅', '❌'):
                if 'task_list_msg' in session:
                    await self.handle_task_list_reaction(reaction, user, session)

    def update_event_time(self, session, emoji):
        if emoji == '⬅️':  
            session['start'] -= timedelta(days=1)
            session['end'] -= timedelta(days=1)
        elif emoji == '➡️': 
            session['start'] += timedelta(days=1)
            session['end'] += timedelta(days=1)
        elif emoji == '⬆️':  
            session['start'] += timedelta(hours=1)
            session['end'] += timedelta(hours=1)
        elif emoji == '⬇️':  
            session['start'] -= timedelta(hours=1)
            session['end'] -= timedelta(hours=1)

    def create_event_embed(self, session):
        embed = discord.Embed(title="Event Details",
                              description="React with the arrows to adjust the event time, ✅ to confirm, or ❌ to cancel.",
                              color=0x00ff00)
        embed.add_field(name="Summary", value=session['summary'], inline=False)
        embed.add_field(name="Date", value=session['start'].strftime('%Y-%m-%d'), inline=True)
        embed.add_field(name="Start Time", value=session['start'].strftime('%H:%M'), inline=True)
        embed.add_field(name="End Time", value=session['end'].strftime('%H:%M'), inline=True)
        return embed
    
    def create_events_list_embed(self, events_dict):
        embed = discord.Embed(title="Today's Events", description="", color=0x00ff00)
        for summary, details in events_dict.items():
            if details['all_day']:
                time_str = "All day"
            else:
                start_time = datetime.fromisoformat(details['start']).strftime('%I:%M %p')
                end_time = datetime.fromisoformat(details['end']).strftime('%I:%M %p')
                time_str = f"{start_time} - {end_time}"
            embed.add_field(name=summary, value=time_str, inline=False)
        return embed

    async def finalize_event_creation(self, user_id):
        session = self.event_creation_sessions.get(user_id)
        if not session:
            return
        start = session['start'].isoformat()
        end = session['end'].isoformat()
        self.add_to_calendar(session['summary'], session['description'], start, end)
        del self.event_creation_sessions[user_id]

    async def handle_task_list_reaction(self, reaction, user, session):
        if str(reaction.emoji) == '❌': 
            await reaction.message.delete()
            del self.event_creation_sessions[user.id]
            return

        current_task_index = session.get('current_task_index', 0)
        if str(reaction.emoji) == '⬅️':  
            current_task_index = max(current_task_index - 1, 0)
        elif str(reaction.emoji) == '➡️': 
            current_task_index = min(current_task_index + 1, len(self.tasks[user.id]) - 1)

        if str(reaction.emoji) == '✅': 
            if 0 <= current_task_index < len(self.tasks[user.id]):
                self.tasks[user.id].pop(current_task_index)
                embed = await self.create_tasks_embed(user.id)
                await reaction.message.edit(embed=embed)
                session['current_task_index'] = min(current_task_index, len(self.tasks[user.id]) - 1)
            return
    
        embed = await self.create_tasks_embed(user.id, current_task_index)
        await reaction.message.edit(embed=embed)
        session['current_task_index'] = current_task_index
        await reaction.remove(user)
    
    @tasks.loop(seconds=600)
    async def daily_message_task(self):
        now_utc = datetime.now(pytz.utc)
        now_est = now_utc.astimezone(pytz.timezone('America/New_York'))
        print(f"Current EST time: {now_est.strftime('%H:%M:%S')}")  
        if now_est.hour == 8:
            print("It's time to send daily messages.")  
            await self.send_daily_messages()
            await asyncio.sleep(20)
    
    async def send_daily_messages(self):
        channel = self.get_channel(self.channel_id)
        if channel:
            await channel.send("Good morning! Here are everyone's tasks and events for today:")
            
            if not self.tasks:
                await channel.send("There are no tasks for anyone today.")
                return

            for user_id, tasks in self.tasks.items():
                try:
                    user = await self.fetch_user(user_id) 
                    if tasks:
                        embed = await self.create_tasks_embed(user_id)
                        await channel.send(f"{user.mention}, here are your tasks for today:", embed=embed)
                    else:
                        await channel.send(f"{user.mention}, you have no tasks for today.")
                except discord.NotFound:
                    print(f"Could not find user with ID: {user_id}")
                except discord.HTTPException as e:
                    print(f"Failed to send message: {e}")
        else:
            print("Channel not found.")

if __name__ == "__main__":
    intents = discord.Intents.default()
    intents.messages = True
    intents.reactions = True
    intents.guilds = True
    intents.message_content = True
    bot = FernBot(intents=intents, channel_id=CHANNEL_ID, calendar_id=private_calendar_id)
    bot.run(TOKEN)