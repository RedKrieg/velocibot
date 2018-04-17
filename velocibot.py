#!python3

import datetime
import discord
import json
from sqlalchemy import Column, DateTime, Interval, Boolean, String
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.exc import NoResultFound

Base = declarative_base()

class Member(Base):
    __tablename__ = 'members'
    id = Column(String, primary_key=True)
    name = Column(String)
    last_join = Column(DateTime)
    total_time = Column(Interval)
    in_chat = Column(Boolean)

engine = create_engine('sqlite:///member_tracker.sqlite')
session = sessionmaker()
session.configure(bind=engine)
Base.metadata.create_all(engine)

def update_total_time(member):
    now = datetime.datetime.now()
    member.total_time += now - member.last_join
    member.last_join = now

client = discord.Client()
@client.event
async def on_voice_state_update(before, after):
    s = session()
    add_member = False
    try:
        member = s.query(Member).filter(Member.id == before.id).one()
    except NoResultFound:
        member = Member(
            id=before.id,
            name=before.nick if before.nick else before.name,
            last_join=datetime.datetime.now(),
            total_time=datetime.timedelta(0),
            in_chat=False
        )
        add_member = True
    if after.voice.voice_channel is None:
        if member.in_chat:
            member.in_chat = False
            update_total_time(member)
        print("{} left voice.  Total time: {}".format(
            member.name, member.total_time
        ))
    else:
        if member.in_chat:
            if after.voice.is_afk:
                member.in_chat = False
                update_total_time(member)
        else:
            member.in_chat = True
            member.last_join = datetime.datetime.now()
        print("{} joined voice.  Total time: {}".format(
            member.name, member.total_time
        ))
    if add_member:
        s.add(member)
    s.commit()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.channel.name != "admins":
        return

    if message.content.startswith('!velocistats'):
        parts = message.content.split()
        s = session()
        if len(parts) > 1 and parts[1].startswith('<@'):
            user_id = parts[1].strip('<@>')
            try:
                member = s.query(Member).filter(Member.id == user_id).one()
            except NoResultFound:
                await client.send_message(message.channel, "User not found!")
                return
            if member.in_chat:
                update_total_time(member)
                s.commit()
            await client.send_message(
                message.channel,
                "User {0.name} has a total chat time of {0.total_time}".format(
                    member
                )
            )
        else:
            members = s.query(Member).order_by(
                Member.total_time.desc()
            ).limit(10).all()
            embed = discord.Embed(
                title="Current Top Voice Users",
                type="rich"
            )
            for member in members:
                if member.in_chat:
                    update_total_time(member)
                embed.add_field(
                    name=member.name,
                    value=member.total_time,
                    inline=True
                )
            s.commit()
            await client.send_message(
                message.channel,
                embed=embed
            )


@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')
    s = session()
    members = s.query(Member).all()
    for member in members:
        member.in_chat = False
    for channel in client.get_all_channels():
        for member in channel.voice_members:
            if not member.voice.is_afk:
                try:
                    db_member = s.query(Member).filter(
                        Member.id == member.id
                    ).one()
                    db_member.in_chat = True
                    db_member.last_join = datetime.datetime.now()
                except NoResultFound:
                    db_member = Member(
                        id=member.id,
                        name=member.nick if member.nick else member.name,
                        last_join=datetime.datetime.now(),
                        total_time=datetime.timedelta(0),
                        in_chat=True
                    )
                    s.add(db_member)
    s.commit()

with open('token.json') as f:
    token = json.load(f)['token']
    
client.run(token)
