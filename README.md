## Artemis (AssistantBOT), a flair enforcer and statistics bot for any subreddit!

* Looking for an easy-to-use bot to help make sure your community's submitters remember to choose a post flair? 
* Want more detailed and extensive statistics on the health and growth of your community? 

**Artemis (AssistantBOT)** is an easy-to-use and helpful Reddit bot written by a moderator *for* moderators to assist them with organizing and gaining insights into their own communities. (Now used on 1,500+ subreddits with over 120 million subscribers and 11,000 moderators combined!)

**Feel free to comment below if you have questions about Artemis.** Or if you prefer Discord, click **[this link](https://discordapp.com/invite/K3yu8g8).**

*This is an edited repost of previous introduction posts, which have now been automatically archived.* ([I](https://www.reddit.com/user/AssistantBOT/comments/9usj60/introduction_to_artemis_uassistantbot/), [II](https://www.reddit.com/user/AssistantBOT/comments/bm11lh/introduction_to_artemis_uassistantbot_ii/), [III](https://www.reddit.com/r/AssistantBOT/comments/dc6i1a/introduction_to_artemis_uassistantbot_iii/), [IV](https://www.reddit.com/r/AssistantBOT/comments/g34kmk/introduction_to_artemis_uassistantbot_round_iv/), [V](https://www.reddit.com/r/AssistantBOT/comments/jdnged/introduction_to_artemis_uassistantbot_round_v/).)


## Functions (TL;DR)

Artemis has two primary functions:

1. **Recording useful statistics for your subreddit**. Artemis will compile statistics on the following and format it in a summary wikipage that's updated daily (see the sidebar on New Reddit or mobile of this subreddit for examples). This wikipage includes:
    * A monthly statistics breakdown of your community's posts and its activity (most active days, top submitters/commenters, top-voted posts).
    * Daily subscriber growth, both future and historical, as well as past and future subscriber milestones. (replacement and complement for [FrontPageMetrics](http://frontpagemetrics.com/)).
    * Traffic data, including the average uniques and pageviews for your community and its estimated traffic for the current month.
2. **Enforcing post flairs on your subreddit**. Artemis will help make sure submitters choose an appropriate flair for their post. (flair enforcing can be turned off, if desired)
    * Artemis can especially help catch any posts that fall through the cracks of Reddit's own post requirements.

Other Artemis functions include, but are not limited to:

* Restricting certain post flairs to certain days of the week.
* Associating certain post flairs with Reddit tags like NSFW, Spoiler, or OC. 
* A breakdown of the userflairs of your community and how many people have each userflair.

**For more detailed information, please see the [FAQ](https://www.reddit.com/r/AssistantBOT/wiki/faq)**.

## I want Artemis to assist my subreddit!

Awesome! It's super easy to add Artemis as a moderator to your subreddit:

1. Use the guide below to determine what kind of mode suits your subreddit best.
2. Invite **u/AssistantBOT1** (**please note the number!**) from your subreddit's moderators page at `https://www.reddit.com/r/SUBREDDIT/about/moderators` with the most suitable moderator permissions.
3. The bot will accept your invite and reply with a confirmation message. 

Note: Artemis will enforce post flairs for subreddits of any size, but will pause statistics-gathering if a subreddit is below 25 subscribers and resume statistics-gathering when it has reached that threshold.

As of January 2021, the original instance of Artemis is no longer accepting new invites - invites should instead be sent to the instance at **u/AssistantBOT1**.

### Flair Enforcing Modes

Artemis's flair enforcing modes are determined by the [moderator permissions](https://www.reddit.com/r/modhelp/wiki/mod_permissions) it has: 

* `Default` mode
    * If you just want Artemis to provide statistics information and *remind* OPs but **not** remove unflaired posts, invite it with the `Manage Wiki Pages` permission. 
* `Strict` mode (optional)
    * If you'd like Artemis to proactively **remove posts that do not have a flair until their author selects one**, invite it with the `Manage Wiki Pages` *and* the `Manage Posts and Comments` permissions. 
* `+` enhancement (optional, but recommended)
    * If you would like submitters to be able to simply select a flair with a reply to Artemis's flair enforcement messages, also invite Artemis with the `Manage Flair` permission. 
    * This enhancement is recommended as it allows users across all platforms to easily select flairs, even if their Reddit client doesn't allow for flair selection.

Artemis will start enforcing post flairs once it accepts your moderator invite and will generate the first statistics page after midnight UTC. 

Here's a table with a detailed breakdown of what the different flair enforcement modes are:

| Moderator Permissions | Flair Enforcement Actions | Mode Name |
|-----------------------|-------------------|-----------|
| `Manage Wiki Pages` | Flair reminder messages are sent to submitters who submit an unflaired post. | `Default` |
| `Manage Wiki Pages`, `Manage Flair` | Flair reminder messages are sent to submitters who submit an unflaired post. Submitters can select a flair by responding to the messages with a flair text. | `Default+` |
| `Manage Wiki Pages`, `Manage Posts and Comments` | Flair reminder messages are sent to submitters who submit an unflaired post. Unflaired posts are removed until submitters select a flair. | `Strict` |
| `Manage Wiki Pages`, `Manage Posts and Comments`, `Manage Flair` / `Everything` | Flair reminder messages are sent to submitters who submit an unflaired post. Unflaired posts are removed until submitters select a flair. Submitters can select a flair by responding to the messages with a flair text. | `Strict+` |

## Settings

Artemis is explicitly designed to be easy-to-use and consequently by default doesn't have "settings" apart from the moderator permissions noted in the table above. **Moderators can choose to turn off flair enforcing** if they want, retaining only Artemis's statistics-gathering function.

If you are comfortable with code and want to change some finer aspects of flair enforcing, please [see this page](https://www.reddit.com/r/AssistantBOT/wiki/advanced) for information on the optional advanced configuration.

## Data

All of the data that Artemis collects, except for an individual subreddit's traffic data, is publicly available through [Reddit's API](https://www.reddit.com/dev/api/) or through other public data sources like [Pushshift](https://pushshift.io/). Posts and subscriber statistics are pulled once daily and traffic data is pulled every month.

Removing Artemis from a subreddit's moderation team automatically terminates all statistics-gathering for the sub. You can find the source code for Artemis [here](https://github.com/kungming2/AssistantBOT). Artemis is published under the open-source [MIT License](https://opensource.org/licenses/MIT).

## About the Writer

I (u/kungming2) am the writer and maintainer of u/translator-BOT ([Wenyuan](https://www.reddit.com/r/translatorBOT/wiki/wenyuan) and [Ziwen](https://www.reddit.com/r/translatorBOT/wiki/ziwen)), among many others. My bot Wenyuan has been keeping [detailed statistics](https://www.reddit.com/r/translator/wiki/overall_statistics) for r/translator for four years. I wanted to write a new statistics and flair enforcement bot for some of the other communities that I moderate and decided to share it with fellow moderators as well. 
