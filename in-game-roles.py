import os
import json
import discord
import asyncio
from datetime import datetime

client = discord.Client()
last_channel = None
script_dir = os.path.dirname(os.path.realpath(__file__))
script_dir = script_dir+('/' if not script_dir.endswith('/') else '')

def read_json(fp):
    with open(fp, 'r') as f:
        data = json.load(f)
    return data

def write_json(fp, data):
    d = os.path.dirname(fp)
    if not os.path.exists(d):
        os.makedirs(d)
    with open(fp, 'w') as f:
        f.write(json.dumps(data, f, indent=4, sort_keys=True))

def get_config():
    global script_dir
    cf = os.path.join(script_dir, 'config.json')
    if not os.path.exists(cf):
        print ("Config file doesn't exist!")
        import sys
        sys.exit(0)
    return read_json(cf)

config = get_config()

def get_serv_settings(serv_id):
    global script_dir
    fp = os.path.join(script_dir, 'servers', serv_id+'.json')
    if not os.path.exists(fp):
        write_json(fp, read_json(os.path.join(script_dir, 'default_settings.json')))
    return read_json(fp)

def set_serv_settings(serv_id, settings):
    global script_dir
    fp = os.path.join(script_dir, 'servers', serv_id+'.json')
    return write_json(fp, settings)

def ldir(o):
    return '[\n'+(',\n'.join(dir(o)))+'\n]'

def fmsg(m):
    # Format message to display in a code block
    s = '```\n'
    s += str(m)
    s += '\n```'
    return s

def strip_quotes(s):
    chars_to_strip = ['\'', '"', ' ']
    if s:
        while s[0] in chars_to_strip:
            if len(s) <= 1:
                break
            s = s[1:]
        while s[-1] in chars_to_strip:
            if len(s) <= 1:
                break
            s = s[:-1]
    return s

def ascii_only(s):
    ns = ""
    printable_chars = list([chr(i) for i in range(32,127)])
    for c in s:
        if c in printable_chars:
            ns += c
        else:
            ns += '_'
    return ns


def log(msg, server=None):
    text = datetime.now().strftime("%Y-%m-%d %H:%M")
    text += ' '
    if server:
        text += '['+server.name+']'
        text += ' '
    text += str(ascii_only(msg))
    print(text)

async def echo (msg, channel='auto', server=None):
    global last_channel
    if channel == 'auto':
        channel = last_channel
    elif channel == None:
        log(msg, server)
        return
    else:
        last_channel = channel
    await catch_http_error(client.send_message, channel, fmsg(msg))
    return

async def catch_http_error (function, *args, **kwargs):
    try:
        if args or kwargs:
            if args and not kwargs:
                r = await function(*args)
            elif kwargs and not args:
                r = await function(**kwargs)
            else:
                r = await function(*args, **kwargs)
        else:
            r = await function()
        return r
    except discord.errors.HTTPException:
        log ("   !! ENCOUNTERED HTTP ERROR !!")

def current_games_dict(settings, server):
    whitelist = settings['whitelist']  # TODO
    gamelist = settings['gamelist']

    need_settings_update = False
    d = {}
    for g in gamelist:
        d[g] = []
    for m in server.members:
        if m.game:
            gname = str(m.game)
            if gname in d:
                d[gname].append(m)
            else:
                if m.name not in settings['ignoreusers']:  # Don't log discovery of games for new users, but we still need to store it.
                    log ("Discovered new game! " + gname)
                d[gname] = [m]
                gamelist.append(gname)
                need_settings_update = True
    if need_settings_update:
        settings['gamelist'] = gamelist
        set_serv_settings(server.id, settings)

    return d

async def update_roles(server, channel=None):
    settings = get_serv_settings(server.id)
    if not settings['enabled']:
        return

    whitelist = settings['whitelist']
    blacklist = settings['blacklist']
    aliases = settings['aliases']
    members = server.members
    roles = [r.name for r in server.roles]
    cgd = current_games_dict(settings, server)
    for g in cgd:
        num_players = len(cgd[g])

        gname = g
        if g in aliases:
            gname = aliases[g]

        is_on_whitelist = g in whitelist or gname in whitelist
        is_not_on_blacklist = g not in blacklist and gname not in blacklist

        if gname not in roles:
            role = None
            if is_not_on_blacklist:
                if not settings['whitelistonly'] or is_on_whitelist:
                    if (num_players >= settings['playerthreshold'] or is_on_whitelist):
                        role = await catch_http_error(client.create_role, server, name=gname, hoist=True)
                        await echo ("Created role "+gname, channel, server)
        else:
            for r in server.roles:
                if r.name == gname:
                    role = r
                    break
        for m in members:
            current_roles = m.roles
            should_have_role = False
            if m in cgd[g]:
                if m.name not in settings['ignoreusers']:
                    if is_not_on_blacklist:
                        if not settings['whitelistonly'] or is_on_whitelist:
                            if (num_players >= settings['playerthreshold'] or is_on_whitelist):
                                should_have_role = True
                                if role not in current_roles:
                                    if get_serv_settings(server.id)['enabled']:  # Just to be sure it wasn't disabled during this process
                                        await echo ("Assign role " + role.name + " to " + m.name, channel, server)
                                        await catch_http_error(client.add_roles, m, role)
            if not should_have_role:
                if role in current_roles:
                    await echo ("Removing role " + role.name + " from " + m.name, channel, server)
                    await catch_http_error(client.remove_roles, m, role)

@client.event
async def on_message(message):
    if message.author == client.user:
        # Don't respond to self
        return

    # Commands
    if message.content.startswith('ig~'):
        msg = message.content[3:]  # Remove prefix
        split = msg.split(' ')
        cmd = split[0]
        params = split[1:]
        params_str = ' '.join(params)

        server = message.server
        channel = message.channel
        settings = get_serv_settings(server.id)

        # Restricted commands
        user_role_ids = list([r.id for r in message.author.roles])
        if not settings['requiredrole'] or settings['requiredrole'] in user_role_ids:
            if cmd == 'enable':
                if settings['enabled']:
                    await echo("Already enabled. Use 'ig~disable' to turn off.", channel)
                else:
                    await echo("Enabling automatic role assignments based on current game. Turn off with 'ig~disable'.", channel)
                    settings['enabled'] = True
                    set_serv_settings(server.id, settings)

            elif cmd == 'disable':
                if not settings['enabled']:
                    await echo("Already disabled. Use 'ig~enable' to turn on.", channel)
                    log("Enabling", server)
                else:
                    await echo("Disabling automatic role assignments and removing roles from users. Turn on again with 'ig~enable'.", channel)
                    log("Disabling", server)
                    settings['enabled'] = False
                    set_serv_settings(server.id, settings)

                    cgd = current_games_dict(settings, server)
                    aliases = settings['aliases']
                    for g in cgd:
                        gname = g
                        if g in aliases:
                            gname = aliases[g]
                        for r in server.roles:
                            if r.name == gname:
                                for m in server.members:
                                    if r in m.roles:
                                        await catch_http_error(client.remove_roles, m, r)
                                break
            
            elif cmd == 'list':
                msg = "Whitelist:\n"
                l = settings['whitelist']
                if l:
                    for g in l:
                        msg += ' * \'' + g + '\'\n'
                else:
                    msg += "* No games in whitelist. Add some with 'ig~add [Game name]'"
                await echo(msg, channel)

                msg = "Blacklist:\n"
                l = settings['blacklist']
                if l:
                    for g in l:
                        msg += ' * \'' + g + '\'\n'
                else:
                    msg += "* No games in blacklist. Add some with 'ig~remove [Game name]'"
                await echo(msg, channel)
                
                msg = "Aliases:\n"
                a = settings['aliases']
                if a:
                    for g in a:
                        msg += ' * \'' + g + '\'  >  \'' + a[g] + '\'\n'
                else:
                    msg += "* No aliases. Add some with 'ig~alias [Actual game name] >> [New name]'"
                await echo(msg, channel)

                msg = "Currently played games:\n"
                d = {}
                for m in server.members:
                    if m.game:
                        gname = str(m.game)
                        if gname in d:
                            d[gname] += 1
                        else:
                            d[gname] = 1
                d = sorted(d.items(), key=lambda x: x[1])  # Creates a tuple version of sorted dict
                for t in d:
                    msg += ' * \'' + t[0] + '\' (' + str(t[1]) + ')\n'
                await echo(msg, channel)
            
            elif cmd == 'add':
                gname = strip_quotes(params_str)

                if not gname:
                    await echo("Incorrect syntax for add command. Should be: 'ig~add [Game name]' (without square brackets).", channel)
                else:
                    if gname not in settings['whitelist']:
                        await echo("Adding '" + gname + "' to the whitelist", channel)
                        settings['whitelist'].append(gname)
                    else:
                        await echo("'" + gname + "' is already on the whitelist", channel)

                    if gname in settings['blacklist']:
                        await echo("Removing '" + gname + "' from the blacklist", channel)
                        settings['blacklist'].remove(gname)
                
                set_serv_settings(server.id, settings)
            
            elif cmd == 'alias':
                gsplit = params_str.split('>>')
                if len(gsplit) != 2 or not gsplit[0] or not gsplit[-1]:
                    await echo("Incorrect syntax for alias command. Should be: 'ig~alias [Actual game name] >> [New name]' (without square brackets).", channel)
                else:
                    gname = strip_quotes(gsplit[0])
                    aname = strip_quotes(gsplit[1])
                    oname = gname
                    if gname in settings['aliases']:
                        oaname = settings['aliases'][gname]
                        oname = oaname
                        await echo("'" + gname + "' already has an alias ('" + oaname + "'), it will be replaced with '" + aname + "'.", channel)
                    else:
                        await echo("'" + gname + "' will now be shown as '" + aname + "'.", channel)
                    settings['aliases'][gname] = aname
                    set_serv_settings(server.id, settings)

                    # Edit role with old name
                    for r in server.roles:
                        if r.name == oname:
                            await catch_http_error(client.edit_role, server, r, name=aname)

            elif cmd == 'movetotop':
                # TODO error handling (e.g. no param)
                gname = strip_quotes(params_str)
                success = False
                
                if gname in settings['whitelist']:
                    success = True
                    settings['whitelist'].remove(gname)
                    settings['whitelist'].insert(0, gname)
                if gname in settings['gamelist']:
                    success = True
                    settings['gamelist'].remove(gname)
                    settings['gamelist'].insert(0, gname)

                if success:
                    await echo("Moving '" + gname + "'' to the top!", channel)
                    set_serv_settings(server.id, settings)
                else:
                    await echo("Can't find '" + gname + "'' on either gamelist or whitelist. Make sure you use the original game name, not an alias.", channel)                

            elif cmd == 'remove':
                gname = strip_quotes(params_str)

                if not gname:
                    await echo("Incorrect syntax for remove command. Should be: 'ig~remove [Game name]' (without square brackets).", channel)
                else:
                    if gname not in settings['blacklist']:
                        await echo("Adding '" + gname + "' to the blacklist", channel)
                        settings['blacklist'].append(gname)
                    else:
                        await echo("'" + gname + "' is already on the blacklist", channel)

                    if gname in settings['whitelist']:
                        await echo("Removing '" + gname + "' from the whitelist", channel)
                        settings['whitelist'].remove(gname)
                    
                    set_serv_settings(server.id, settings)
                    
                    for r in server.roles:
                        if r.name == gname:
                            await catch_http_error(client.delete_role, server, r)
                            await echo("Deleting '" + gname + "' role", channel)
                            break

            elif cmd == 'playerthreshold':
                value = strip_quotes(params_str)
                try:
                    value = int(value)
                except ValueError:
                    await echo("That doesn't make any sense. Expected input is 'ig~playerthreshold X' where X is a number.", channel)
                else:
                    await echo("Threshold set! Only games with " + str(value) + " or more current players will be included.", channel)
                    settings['playerthreshold'] = value
                    set_serv_settings(server.id, settings)

            elif cmd == 'clearwhitelist':
                await echo("Clearing the whitelist.", channel)
                settings['whitelist'] = []
                set_serv_settings(server.id, settings)

            elif cmd == 'whitelistonly':
                settings['whitelistonly'] = not settings['whitelistonly']
                if settings['whitelistonly']:
                    await echo("Now only whitelisted games will be shown.", channel)
                else:
                    await echo("Now all games will be shown, as long as they have more than " + str(settings['playerthreshold']) + " players. Whitelisted games will always show.", channel)
                set_serv_settings(server.id, settings)

            elif cmd == 'ignore':
                user = strip_quotes(params_str)
                if user not in settings['ignoreusers']:
                    settings['ignoreusers'].append(user)
                    await echo("Ignoring user \""+user+"\".", channel)
                else:
                    settings['ignoreusers'].remove(user)
                    await echo("\""+user+"\" was previously ignored and will now be watched.", channel)
                set_serv_settings(server.id, settings)

            elif cmd == 'listroles':
                l = ["ID" + ' '*18 + "\"Name\"  (Creation Date)"]
                l.append('='*len(l[0]))
                roles = sorted(server.roles, key=lambda x: x.created_at)
                for r in roles:
                    l.append(r.id+"  \""+r.name+"\"  (Created on "+r.created_at.strftime("%Y/%m/%d")+")")
                await echo('\n'.join(l), channel)

            elif cmd == 'restrict':
                role_id = strip_quotes(params_str)
                if not role_id:
                    await echo ("You need to specifiy the id of the role. Use 'ig~listroles' to see the IDs of all roles, then do 'ig~restrict 123456789101112131'", channel)
                else:
                    valid_ids = list([r.id for r in server.roles])
                    if role_id not in valid_ids:
                        await echo (valid_ids, channel)
                        await echo (role_id + " is not a valid id of any existing role. Use 'ig~listroles' to see the IDs of all roles.", channel)
                    else:
                        role = None
                        for r in server.roles:
                            if r.id == role_id:
                                role = r
                                break
                        if role not in message.author.roles:
                            await echo ("You need to have this role yourself in order to restrict commands to it.", channel)
                        else:
                            settings['requiredrole'] = role.id
                            set_serv_settings(server.id, settings)
                            await echo ("From now on, most commands will be restricted to users with the \"" + role.name + "\" role.", channel)

        # Commands all users can do
        if cmd == 'ignoreme':
            user = message.author.name
            if user not in settings['ignoreusers']:
                settings['ignoreusers'].append(user)
                await echo("Ignoring user \""+user+"\".", channel)
            else:
                settings['ignoreusers'].remove(user)
                await echo("\""+user+"\" was previously ignored and will now be watched.", channel)
            set_serv_settings(server.id, settings)


async def background_task():
    await catch_http_error(client.wait_until_ready)
    global config
    counter = 0
    while not client.is_closed:
        counter += 1
        for s in client.servers:
            await update_roles(s, None)
        await asyncio.sleep(config['background_interval'])


@client.event
async def on_ready():
    print ('Logged in as')
    print (client.user.name)
    print (client.user.id)
    curtime = datetime.now().strftime("%Y-%m-%d %H:%M")
    print (curtime)
    print ('-'*len(client.user.id))

client.loop.create_task(background_task())
client.run(config['token'])
