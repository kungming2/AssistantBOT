#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""The text component is a collection of responses and text used by
Artemis in its interactions with moderators, regular users, and wiki
pages.
"""

BOT_DISCLAIMER = ("\n\n---\n^Artemis: ^a ^moderation ^assistant ^for ^r/{0} ^| "
                  "[^Contact ^r/{0} ^mods](https://www.reddit.com/message/compose?to=%2Fr%2F{0}) "
                  "^| [^Bot ^Info/Support](https://www.reddit.com/r/AssistantBOT/)")

# These are responses to moderator actions.
MSG_MOD_INIT_ACCEPT = """
Thanks for letting me assist the r/{0} \
[moderator team](https://www.reddit.com/r/{0}/about/moderators)! Flair \
enforcing is currently set to `{5}` [mode](https://www.reddit.com/r/\
AssistantBOT/wiki/faq#wiki_flair_enforcing).

{4}

{1}

{3}

{2}

{6}

---

* Moderators can [send me new modmail messages]\
(https://mod.reddit.com/mail/create) from a subreddit \
([instructions here]\
(https://i.imgur.com/MnXVrFT.gifv)) to access some other options.
    * Just include the relevant **action word** in the **subject** of \
    a *modmail message*; anything in the message body is fine.
    * Artemis should *not* have the `mail` moderator permission, or \
`full` moderator permissions, or these action messages will become \
classified as modmail "discussions" and be inaccessible to me.

| Action Word | Function                                                                          |
|-------------|-----------------------------------------------------------------------------------|
| `Disable`   | Completely disable flair enforcing on r/{0}.                                      |
| `Enable`    | Re-enable flair enforcing on r/{0}.                                               |
| `Example`   | See an example of r/{0}'s flair enforcement message to users.                     |
| `Update`    | Create or update an advanced configuration page for r/{0}. *[See here for details]\
(https://www.reddit.com/r/AssistantBOT/wiki/advanced)*. |
| `Revert`    | Revert to the default configuration and clear all advanced settings.              |
| `Takeout`   | Export r/{0}'s Artemis data as JSON. *[See here for details]\
(https://www.reddit.com/r/AssistantBOT/wiki/faq#wiki_takeout)*. |
| `Query`     | Query Artemis's actions database for individual posts. *[See here for details]\
(https://www.reddit.com/r/AssistantBOT/wiki/faq#wiki_query)*. |

---

* I update subreddit statistics daily after [midnight UTC](https://time.is/UTC).
* Please [contact my creator](https://www.reddit.com/message/compose?to=kungming2&subject=\
About+Artemis+%28From+r%2F{0}%29) u/kungming2 if you have any questions.
* Feel free to check out r/AssistantBOT for updates, statistics, and more!

Have a good day!
"""
MSG_MOD_INIT_PROFILE = """
👤 This moderation invite appears to be for a redditor's user profile. Unfortunately user \
profiles *do not* have [post flairs](https://www.reddithelp.com/en/categories/using-reddit/\
profiles/profile-moderation-tools) and Artemis is therefore unusable on them.

If this is in error, please make a comment on r/AssistantBOT with this subreddit's name. Thanks!
"""
MSG_MOD_INIT_QUARANTINED = '''
☣️ It appears that this subreddit may be a [quarantined community]\
(https://www.reddithelp.com/en/categories/rules-reporting/account-and-community-restrictions\
/quarantined-subreddits). Unfortunately, Reddit explicitly makes it difficult, if not impossible, \
to [access data about quarantined communities through its public API](https://redd.it/3fx3gt). \
Consequently, Artemis is unable to assist quarantined communities.

Sorry for any inconvenience!
'''
MSG_MOD_INIT_REDIRECT = """
🈵 Thanks for inviting me to assist the r/{0} \
[moderator team](https://www.reddit.com/r/{0}/about/moderators)! \
We are currently asking new subreddits to invite my alternate accounts \
to moderate instead, in order to spread out the load on Reddit's API. 

**Please [send a moderator invite]\
(https://www.reddit.com/r/{0}/about/moderators) to the alternate \
account at u/{1}**, and I'll take care of the rest for you.

Sorry for any inconvenience!
"""
MSG_MOD_INIT_ALREADY_MONITORED = """
⁉️ It looks like Artemis is already active on r/{0} with its u/{1} \
account. If you would like to move your subreddit to a different \
instance of Artemis, please remove any of its accounts from the r/{0} \
moderator list, and send an invite to the bot account you want it to \
be active on.

The alternate account **u/{2}** is currently available.
"""
MSG_MOD_INIT_MINIMUM = """
⏸️ This subreddit currently has fewer than {0} subscribers, so I've paused statistics \
gathering for now. I will automatically resume statistics gathering once it reaches that \
milestone (it is currently {1} subscribers short).
"""
MSG_MOD_INIT_NON_MINIMUM = """
📊 I will post statistics for the community daily at **[this wiki page]\
(https://www.reddit.com/r/{}/wiki/assistantbot_statistics)**. \
(I recommend bookmarking this page for easy access.)
"""
MSG_MOD_INIT_STRICT = '''
🔨 Since I have the `posts` moderator permission, I will *remove* posts \
without any flair and automatically \
*restore and approve* them once a flair is selected. Unflaired posts older than 24 hours are \
considered abandoned by their submitter and will not be restored.

To disable post removals but continue flair enforcement via reminder messages, simply uncheck \
my `posts` moderator permission [here](https://www.reddit.com/r/{0}/about/moderators). \
Please keep in mind that I do not act on moderators' posts by default, so please use a \
throwaway account if you are testing my functions out.

**I also recommend turning on the `Require post flair` setting in this subreddit's \
[post requirements](https://new.reddit.com/r/{0}/about/settings) for best results.**
'''
MSG_MOD_INIT_MESSAGING = '''
📨 Since I also have the `flair` moderator permission, submitters can simply reply to my \
flair enforcement messages with the text of the flair they want to select, and I will \
automatically *assign that flair to and approve* their post.
'''
MSG_MOD_INIT_NO_FLAIRS = '''
---

🈳 **It appears that there are no public post flairs associated with this subreddit.** \
If you'd like, please check out these Reddit Help articles ([New Reddit]\
(https://mods.reddithelp.com/hc/en-us/articles/360010513191-Post-Flair), \
[Old Reddit](https://mods.reddithelp.com/hc/en-us/articles/360002598912-Flair)) for guidance on \
how to set up and enable post flairs for your subreddit.

If you have already created post flairs, they may not be set to be \
*publicly* selectable. If this is the case, please make sure the option for submitters to assign \
their own post flair is selected, ([New Reddit](https://i.imgur.com/86mVlzQ.png), [Old Reddit]\
(https://i.imgur.com/V2YqXQG.png)) and then send a modmail message with `Enable` in the subject \
line to re-enable flair enforcing.

🔒 **I have disabled flair enforcing on the subreddit for now since there are no post flairs.** \
You can re-enable flair enforcing by following the instructions below.
'''
MSG_MOD_INIT_NEED_WIKI = '''
😕 It appears that I do not have the `wiki` mod permission to create and update a subreddit's \
statistics page. If you would still like me to assist the mod team with statistics, please grant \
me the `wiki` [mod permission here](https://www.reddit.com/r/{}/about/moderators). Thanks!
'''
MSG_MOD_INSTANCE_MIGRATION = '''
---

📦 It appears that this subreddit was previously monitored by an instance of Artemis (`{0}`). \
Any data associated with r/{1} has been ported from the old instance's databases for use with \
this instance's (`{2}`).
'''
MSG_MOD_RESP_ENABLE = ("🔓 Flair enforcing is now **ENABLED** on r/{}. "
                       "Artemis will send reminder messages to users "
                       "who submit posts without selecting a post flair.")
MSG_MOD_RESP_DISABLE = ("🔒 Flair enforcing is now **DISABLED** on r/{}. "
                        "Artemis will *NOT* send reminder messages "
                        "to users who submit posts without selecting a post flair.")
MSG_MOD_RESP_USERFLAIR = '👥 Userflair statistics gathering is now **{}** on r/{}.'
MSG_MOD_RESP_USERFLAIR_NEED_FLAIR = '''
😕 It appears that I do not have the `flair` mod permission to gather userflair statistics. \
If you would still like me to assist with userflair statistics, please grant me the `flair` \
[mod permission here](https://www.reddit.com/r/{}/about/moderators) and resend this message. \
Thanks!
'''
MSG_MOD_STATISTICS_FIRST = """
Hey there moderators of r/{0}!

I wanted to give you a heads-up that your community statistics have just been posted at \
**[this wiki page](https://www.reddit.com/r/{0}/wiki/assistantbot_statistics)**. There's also a \
handy [guide here](https://www.reddit.com/r/AssistantBOT/wiki/guide) that explains each section \
of the page.

Please note that this is a *one-time message* to inform you that the statistics wiki page has \
been set up. \
Subsequent updates will be performed silently after [midnight UTC](https://time.is/UTC). \
This wiki page is by default only visible to moderators and is *not* listed on the subreddit's \
[general list of wiki pages](https://www.reddit.com/r/{0}/wiki/pages/).

Have a good day!
"""
MSG_MOD_TAKEOUT = '''
🥡 Here's your takeout data from Artemis formatted in [JSON](https://en.wikipedia.org/wiki/JSON),\
 an open-standard file format that is easy for humans to read and write and easy for machines to \
parse and generate.

This link is hosted on my [Pastebin](https://pastebin.com/u/assistantbot) \
and is **only viewable for one hour** \
by those who have the link. The data will be automatically deleted after that, so please download \
it before deletion.

#### [Artemis Takeout Data for r/{}]({})
'''
MSG_MOD_TAKEOUT_NONE = '''
🍽️ Unfortunately, there doesn't appear to be any data from r/{} in my database to takeout.
'''
MSG_MOD_QUERY_NONE = '''
🤔 Unfortunately, there doesn't appear to be any valid data in my database from your query.
'''
MSG_MOD_LEAVE = '''
👋 Artemis will no longer be active on r/{}. Have a good day!
'''
# The following are messages to users reminding them to use post flairs.
MSG_USER_FLAIR_SUBJECT = "[Notification] ⚠️ Your post on r/{} needs a post flair!"
MSG_USER_FLAIR_BODY = '''
Hey there u/{0},

Thanks for submitting your post to r/{1}!

> **[{8}]({3})**

This is a friendly reminder that this community's moderators have \
asked for all posts to have a *post flair* \
(a relevant tag or category).

{9}

{5}

**You can select a post flair by**:

* ➡️️ Using Reddit's interface to pick the one you want. \
View a GIF below to show you how!
    * *[Mobile](https://i.imgur.com/qPJlLPH.gifv)* • \
*[Desktop (New)](https://i.imgur.com/1jzmEqK.gifv)* • \
*[Desktop (Old)](https://i.imgur.com/V8NYT6N.gifv)* • \
*[Mobile Web](https://i.imgur.com/Hna2rD7.gifv)*
    * Third-party apps: *[Apollo](https://i.imgur.com/X4EaiI1.gifv)*  \
• *[BaconReader](https://i.imgur.com/ZJnBmEk.gifv)* • \
*[Boost](https://i.imgur.com/8h4Zpw3.gifv)* • \
*[Relay](https://i.imgur.com/2g7s4jk.gifv)* • \
*[RIF](https://i.imgur.com/179de1o.gifv)*
{7}

**The following post flairs are available**:

{2}

Post flairs help keep this community organized and allow subscribers to easily sort through the \
posts they want to see. [Please contact the mods of r/{1} if you have any questions.]({4}) \
Thank you very much, and {6}!
'''
MSG_USER_FLAIR_BODY_MESSAGING = ("\n* ↩️ *or* replying to this message with just the text of a "
                                 "flair listed below.\n    * Capitalization does not matter.")
MSG_USER_FLAIR_MODMAIL_LINK = ("https://www.reddit.com/message/compose?to=%2Fr%2F{}&subject="
                               "About+My+Unflaired+Post&message="
                               "About+my+post+%5Bhere%5D%28{}%29...")
MSG_USER_FLAIR_REMOVAL = ("**Your post has been removed but will be automatically restored if you "
                          "select a flair for it within 24 hours.** "
                          "We apologize for the inconvenience.\n\n")
MSG_USER_FLAIR_REMOVAL_NO_APPROVE = ("**Your post has been removed but may be restored by a "
                                     "moderator as soon as possible if you select a flair for it"
                                     ".**  We apologize for the inconvenience.\n\n")
MSG_USER_FLAIR_APPROVAL = """
Hey there u/{},

{} a flair for [your post]({})! {}

{}!
"""
MSG_USER_FLAIR_APPROVAL_STRICT = "It has been approved and is now fully visible on r/{}."
# These are templates used on the statistics wiki pages.
WIKIPAGE_BLANK = """
# Statistics by Artemis (u/AssistantBOT)


📊 *This statistics page will be updated after [midnight UTC](https://time.is/UTC) if this \
subreddit has at least {} subscribers.*
"""
WIKIPAGE_TEMPLATE = '''

# Statistics by Artemis (u/AssistantBOT)

{9}[🏹 Info](https://www.reddit.com/r/AssistantBOT/) • \
[❓ FAQ](https://www.reddit.com/r/AssistantBOT/wiki/faq) • \
[🔎️ Guide](https://www.reddit.com/r/AssistantBOT/wiki/guide) • \
[📓 Change Log](https://www.reddit.com/r/AssistantBOT/wiki/changelog) • \
[📒 Mod Log](https://www.reddit.com/r/{0}/about/log/?mod=AssistantBOT) • \
[📮 Contact Bot Author]\
(https://www.reddit.com/message/compose/?to=kungming2&subject=About+Artemis+on+r%2F{0})

{8}

---

*Compiled by Artemis v{5} in {6} seconds and updated on {7} UTC.*

---

## Bot Status

{1}

## Posts

{2}

## Subscribers

{3}

## [Traffic](https://www.reddit.com/r/{0}/about/traffic/)

{4}
'''
# This is a list of goodbye phrases.
# Artemis chooses a random one when sending a message.
GOODBYE_PHRASES = ['Adieu', 'Adiós', 'All the best', 'Au revoir', 'Best regards', 'Cheers', 'Ciao',
                   'Farewell', 'Goodbye', 'Hasta la vista', 'Have a fantastic day',
                   'Have a good one', 'Have a great day', 'Have a nice day',
                   'Keep it real', 'Live long and prosper',
                   'Mahalo', 'May the odds be ever in your favor', 'Namaste', 'Peace', 'Regards',
                   'Sayonara', 'See ya', 'So long', 'Stay awesome', 'Stay healthy',
                   'Stay safe', 'Stay well', 'Take care', 'Take it easy', 'To infinity and beyond',
                   'Toodeloo', 'Tschüss', 'Until next time']
# This is the default Artemis configuration as expressed in YAML.
# In dictionary form it's rendered as:
# {'flair_enforce_approve_posts': True,
#  'flair_enforce_custom_message': None,
#  'flair_enforce_whitelist': [],
#  'userflair_statistics': True,
#  'flair_enforce_moderators': False,
#  'custom_name': 'Artemis'}
ADV_DEFAULT = """
    # -----------------------------------------------------------------
    # INSTRUCTIONS: https://www.reddit.com/r/AssistantBOT/wiki/advanced
    # MODMAIL: https://mod.reddit.com/mail/create
    # -----------------------------------------------------------------
    # This is a configuration page for more advanced and granular settings of Artemis.
    # Everything must be written in valid YAML, which is the same syntax that AutoModerator's uses.
    # To update Artemis's configuration, make your changes below,
    # and then send u/AssistantBOT a *modmail message* from the subreddit you're updating it for
    # with `Update` in the subject line.
    # --------------------------
    # FLAIR ENFORCEMENT SETTINGS
    # --------------------------
    # A boolean determining whether Artemis also sends flair enforcement messages to moderators.
    # Default setting: False
    flair_enforce_moderators: False
    # A boolean determining whether Artemis approves removed posts once flaired by a user or a mod.
    # Please do NOT change this unless you plan on reviewing/approving all removed posts manually!
    # Default setting: True
    flair_enforce_approve_posts: True
    # A string with a custom subreddit-specific message to include in flair enforcement messages.
    # Messages over 500 characters (including spaces) will be truncated.
    flair_enforce_custom_message: ""
    # A list of users that should NOT get flair enforcement messages. (no `u/`, please)
    flair_enforce_whitelist: []
    # A list of moderators to be notified whenever a post is removed. (no `u/`, please)
    # This is most suitable for smaller subreddits with relatively few posts per week.
    flair_enforce_alert_list: []
    # --------------
    # OTHER SETTINGS
    # --------------
    # A boolean determining whether Artemis gathers userflair statistics.
    # Default setting: True if subreddit has at least 50K subscribers, False otherwise.
    userflair_statistics: False
    # A dictionary with up to 3 keys: `nsfw`, `oc`, and `spoiler`.
    # Each key takes a *list* of post flair IDs.
    # If a submission is flaired with one, it will be tagged with the corresponding attribute.
    flair_tags: {}
    # A custom bot name instead of "Artemis" for usage in flair enforcement messages to users.
    # Please do not change this to something too long.
    # Names over 20 characters (including spaces) will be truncated.
    custom_name: "Artemis"
    # A custom goodbye phrase for the bot to use in its flair enforcement messages to users.
    # By default, Artemis chooses a random phrase from a pre-existing list.
    # Please do not change this to something too long.
    # Phrases over 20 characters (including spaces) will be truncated.
    custom_goodbye: ""
"""
CONFIG_GOOD = '''
👍 The data for r/{0} has been updated from the **[advanced configuration page]\
(https://www.reddit.com/r/{0}/wiki/assistantbot_config)** successfully! \
It will be used for your community's [advanced Artemis settings]\
(https://www.reddit.com/r/AssistantBOT/wiki/advanced).

* If this is the first time you've received this message, the advanced configuration page \
has been created and is now ready for moderators to edit.
    * Just send another modmail message with `Update` in the subject line to reload \
any changes you've made.
* Otherwise, this reply serves to confirm that Artemis has processed the configuration data \
and applied those changes.
    * An example flair enforcement message is attached below.
* If you no longer wish to use these settings and would like to revert to the default, \
[send me a new modmail message](https://mod.reddit.com/mail/create) with `Revert` in \
the subject line.
'''
CONFIG_BAD = """
👎 Artemis encountered an error with the advanced configuration data for r/{0}. Please check the \
**[advanced configuration page](https://www.reddit.com/r/{0}/wiki/assistantbot_config)**'s data \
with this [online tool](https://onlineyamltools.com/validate-yaml) and make sure that all the \
necessary variables are [present and of the expected type]\
(https://www.reddit.com/r/AssistantBOT/wiki/advanced#wiki_troubleshooting).

Alternatively, please make sure that Artemis has the required `wiki` [mod permission]\
(https://www.reddit.com/r/{0}/about/moderators).

* Once everything has been fixed, please [send me another modmail message]\
(https://mod.reddit.com/mail/create) with `Update` in the subject line to reload the changes \
you've made.

---

*The following error message was generated by Artemis:*

---

{1}
"""
CONFIG_REVERT = """
🧹 Your subreddit's settings have now been reverted to their regular configuration. \
The content of the **[advanced configuration page]\
(https://www.reddit.com/r/{0}/wiki/assistantbot_config)** has also been reverted to its default \
settings.
"""
