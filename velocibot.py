#!python3

import asyncio
import datetime
import discord
import json
from sqlalchemy import Column, DateTime, Interval, Boolean, String
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound
import sys

# Database setup
Base = declarative_base()

class Member(Base):
    __tablename__ = 'members'
    id = Column(String, primary_key=True)
    name = Column(String)
    last_join = Column(DateTime)
    total_time = Column(Interval)
    in_chat = Column(Boolean)

    def update_total_time(self):
        """Update total_time with time since last_join"""
        now = datetime.datetime.now()
        self.total_time += now - self.last_join
        self.last_join = now

engine = create_engine('sqlite:///member_tracker.sqlite')
session = sessionmaker()
session.configure(bind=engine)
Base.metadata.create_all(engine)

# Discord client
client = discord.Client()

# Helpers
def update_active_users():
    """Updates total_time for all active users"""
    s = session()
    for channel in client.get_all_channels():
        for member in channel.voice_members:
            if not member.voice.is_afk:
                try:
                    dbmember = s.query(Member).filter(
                        Member.id == member.id
                    ).one()
                    dbmember.in_chat = True
                    dbmember.update_total_time()
                except NoResultFound:
                    dbmember = Member(
                        id=member.id,
                        name=member.nick if member.nick else member.name,
                        last_join=datetime.datetime.now(),
                        total_time=datetime.timedelta(0),
                        in_chat=True
                    )
                    s.add(dbmember)
    s.commit()

def check_admin(message):
    """Checks if the message is from an administrator"""
    perms = message.channel.permissions_for(message.author)
    is_admin = perms.administrator
    try:
        for role in message.author.roles:
            if "Admins" in role.name or "Founder" in role.name:
                is_admin = True
                break
    except AttributeError:
        # Bypass for redkrieg to work in private messages
        if str(message.author.id) == "135195179219943424":
            is_admin = True
    return is_admin

def format_timedelta(td):
    """Formats timedelta without microseconds"""
    # Modified from stdlib datetime.timedelta.__str__
    mm, ss = divmod(td.seconds, 60)
    hh, mm = divmod(mm, 60)
    s = "%d:%02d:%02d" % (hh, mm, ss)
    if td.days:
        def plural(n):
            return n, abs(n) != 1 and "s" or ""
        s = ("%d day%s, " % plural(td.days)) + s
    return s


# Background events
async def active_user_update_loop():
    """Reset join times, wait for discord connection, then keep db synced"""
    s = session()
    members = s.query(Member).all()
    now = datetime.datetime.now()
    for member in members:
        member.in_chat = False
        member.last_join = now
    s.commit()
    await client.wait_until_ready()
    while not client.is_closed:
        update_active_users()
        await asyncio.sleep(60)

# Discord events
@client.event
async def on_voice_state_update(before, after):
    """Monitor status updates for voice channels"""
    s = session()
    # prefer nickname in server to actual discord username
    member_name = before.nick if before.nick else before.name
    try:
        member = s.query(Member).filter(Member.id == before.id).one()
        # update member names on each channel join
        member.name = member_name
    except NoResultFound:
        member = Member(
            id=before.id,
            name=member_name,
            last_join=datetime.datetime.now(),
            total_time=datetime.timedelta(0),
            in_chat=False
        )
        s.add(member)
    if after.voice.voice_channel is None:
        if member.in_chat:
            member.in_chat = False
            member.update_total_time()
        try:
            channel_name = before.voice.voice_channel.name
        except AttributeError:
            channel_name = "Unknown"
        print("{} left voice channel {}.  Total time: {}".format(
            member.name,
            channel_name,
            member.total_time
        ))
    else:
        if member.in_chat:
            # Don't consider deafened or afk users as active
            if after.voice.is_afk or after.voice.self_deaf or after.voice.deaf:
                # This logic breaks if the user is server deafened and
                # self-deafens as well.  Need to think through.
                member.in_chat = False
                member.update_total_time()
        else:
            member.in_chat = True
            member.last_join = datetime.datetime.now()
        try:
            channel_name = after.voice.voice_channel.name
        except AttributeError:
            channel_name = "Private"
        print("{} joined voice channel {}.  Total time: {}".format(
            member.name,
            channel_name,
            member.total_time
        ))
    s.commit()
    sys.stdout.flush()

@client.event
async def on_message(message):
    """Handles incoming messages"""
    if message.author == client.user:
        return

    if not check_admin(message):
        return

    if message.content.startswith('!velocistats'):
        s = session()
        if len(message.mentions) > 0:
            for member in message.mentions:
                try:
                    dbmember = s.query(Member).filter(
                        Member.id == member.id
                    ).one()
                except NoResultFound:
                    await client.send_message(
                        message.channel,
                        "User {} not found!".format(
                            member.nick if member.nick else member.name
                        )
                    )
                    continue
                if dbmember.in_chat:
                    dbmember.update_total_time()
                    s.commit()
                await client.send_message(
                    message.channel,
                    "User {0} has a total chat time of {1}".format(
                        dbmember.name,
                        format_timedelta(dbmember.total_time)
                    )
                )
        elif message.content.startswith('!velocistats low'):
            members = s.query(Member).order_by(
                Member.total_time.asc()
            ).filter(
                Member.name.startswith('-=[ V ]=-')
            ).limit(10).all()
            msg = [ """Current Lowest Voice Users\n\n```""" ]
            for member in members:
                if member.in_chat:
                    member.update_total_time()
                msg.append(
                    "{0: <40}{1: >25}\n".format(
                        member.name,
                        format_timedelta(member.total_time)
                    )
                )
            msg.append("""```""")
            s.commit()
            await client.send_message(
                message.channel,
                ''.join(msg)
            )
        else:
            members = s.query(Member).order_by(
                Member.total_time.desc()
            ).limit(10).all()
            msg = [ """Current Top Voice Users\n\n```""" ]
            for member in members:
                if member.in_chat:
                    member.update_total_time()
                msg.append(
                    "{0: <40}{1: >25}\n".format(
                        member.name,
                        format_timedelta(member.total_time)
                    )
                )
            msg.append("""```""")
            s.commit()
            await client.send_message(
                message.channel,
                ''.join(msg)
            )

@client.event
async def on_ready():
    """Print out some status info on connect"""
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')
    sys.stdout.flush()

# Configuration
with open('token.json') as f:
    token = json.load(f)['token']
    
# Run it
client.loop.create_task(active_user_update_loop())
client.run(token)
