## Examples

This section contains examples of the messages and text that Artemis generates when assisting moderators.

#### Example Flair Enforcement Message

This message is sent to users who do not select a flair for their post:

---

Hey there, u/USERNAME,
    
Thanks for your submission to r/SUBREDDIT! This is a friendly reminder that the moderators of this community have asked for all posts in r/SUBREDDIT to have a *post flair* - in other words, a relevant tag or category. 
    
**Here's how to select a flair for your submission**: 
    
*[Mobile](https://i.imgur.com/q9OIOaU.gifv)* | *[Tablet](https://i.imgur.com/I35qWPZ.gifv)* | *[Desktop (New)](https://i.imgur.com/AAjN8en.gifv)* | *[Desktop (Old)](https://i.imgur.com/RmZr6Cv.gifv)*.
    
**The following post flairs are available on r/SUBREDDIT**:
    
    
* Flair 1
* Flair 2
* ...
        
     
Post flairs help keep r/SUBREDDIT organized and allow our subscribers to easily sort through the posts they want to see. Please contact the mods of r/SUBREDDIT if you have any questions. Thank you very much!

---

The following line is also included if `strict` flair enforcement is on:

---

*Your post has been removed but will be automatically restored if you select a flair for it within 24 hours. We apologize for the inconvenience.*

---

#### Example Statistics Page

Check out r/ChineseLanguage's **[live statistics page here](https://www.reddit.com/r/chineselanguage/wiki/assistantbot_statistics)** for an example.

## FAQ

#### Who can use Artemis?

Any subreddit can! Just invite u/AssistantBOT as a moderator with at least the `wiki` permission.

#### What kind of subreddits benefit from using Artemis?

**The subreddits that benefit most from Artemis are those that have a post flair system.** Subreddits with no post flairs will obviously not benefit from flair enforcing.

Subreddits that use their post flairs dynamically to indicate a post's status, like r/translator or r/excel, will likely benefit less from Artemis since an individual post's flair is automatically assigned and constantly changing.

#### When does Artemis update the statistics wiki pages?

Artemis begins to update statistics wiki pages for its monitored subreddits (`r/SUBREDDIT/wiki/assistantbot_statistics`) at midnight UTC.

#### How long does Artemis wait before sending a flair enforcement message?

Artemis acts on posts that are at least five minutes old, to give OPs a chance to select a flair after they submitted. If the post is over five minutes old and still has no flair, Artemis will send the message.

#### Our subreddit wiki is public - why does Artemis need the `wiki` permission? Can't it run with *no* mod permissions?

Artemis needs the `wiki` mod permission for a couple of reasons:

1. So that it can create a new wiki page even if a subreddit has disabled its wiki.
2. So that it can set the statistics wikipage to be only viewable by mods.

#### Why does the "average submissions per day" number seem so high? Especially when compared with my flair table?

The average submissions/comments per day statistic is calculated from [Pushshift's](https://pushshift.io/) data and includes posts that have been removed as well. Your average submissions per day is thus likely to be higher if your subreddit is a frequent target of spammers. This number is an accurate count of *all* posts your community receives.

The flair table only records posts that were *not* removed and is the more accurate count of posts your community actually sees.

#### How do I disable Artemis?

Just remove it as a moderator from your subreddit. 

#### Why can't statistics gathering be turned off?

Gathering statistics helps moderators understand the activity and health of their community. All of the data for statistics (with the exception of traffic) is publicly obtainable, and it is my firm belief that all moderators can benefit from being able to view the statistics that Artemis provides.

#### Who made Artemis?

I'm u/kungming2, and I also wrote and maintain [Wenyuan and Ziwen](https://www.reddit.com/r/translatorbot/) (u/translator-BOT) and u/LEGO_IDEAS_BOT, among others.

#### Why is this bot called Artemis?

Honestly, it's just because I like the name. But perhaps one can think of this bot as [hunting](https://en.wikipedia.org/wiki/Artemis) down both unflaired posts and statistics.

#### Why did you make this bot?

I mod several communities that use post flairs, and it was frustrating to see no effective way to enforce post flairs given that most flair enforcement bots are no longer in use. Furthermore, I wanted to make publicly available some of the statistics-calculating functions I use for Wenyuan and Ziwen for other  moderators to use.  

#### I have a feature suggestion for Artemis.

Feel free to shoot me a message at u/kungming2.

## Technical Details

#### Source Code

You can find Artemis's source code at [this repo on Github](https://github.com/kungming2/AssistantBOT).

#### Other

* Artemis is hosted on a Raspberry Pi 3 that also runs u/translator-BOT and u/LEGO_IDEAS_BOT.
* Artemis is written in Python 3, and with the exception of [PRAW](https://praw.readthedocs.io/en/latest/index.html), only uses built-in Python modules.
