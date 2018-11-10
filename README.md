## Introducing Artemis (u/AssistantBOT), a flair enforcer and statistics bot for YOUR subreddit!

Looking for an easy-to-use bot to help make sure your community's submitters remember to choose a post flair? Want more detailed and extensive statistics on your community? **Artemis (u/AssistantBOT)** is an easy-to-use and helpful bot intended to help moderators with organizing and gaining insights into their own community. It is written by a moderator *for* moderators.


## Functions

Artemis has two primary functions:

1. **Enforcing post flairs on your subreddit**. Artemis will help make sure submitters choose an appropriate flair for their post.
2. **Recording useful statistics for your subreddit**. Artemis will compile statistics on the following and format it in a summary wikipage, updated daily:
    * Your community's posts and top submitters/commenters.
    * Subscriber growth.
    * Traffic growth.

### Flair Enforcing

Many subreddit mods have put time and effort into creating post flairs that not only add visual variety to their community but also help organize their communities' submissions. Being able to see all the posts with the "Art" post flair, for example, can be extremely convenient for people. **Unfortunately, submitters often forget to choose a post flair before or after they submit their post.** Selecting a post flair can be made mandatory on [the redesign](https://www.reddit.com/r/redesign/), but that rule doesn't affect mobile or classic Reddit users.

**Artemis helps enforce flair selection** by doing the following:

* `(default mode)` **Send a reminder message with a list of the subreddit's post flairs** to the submitter if they have not selected a flair within five minutes of submission. 
* `(optional strict mode)` The above, **and remove the unflaired submission until the submitter selects a flair**. Artemis will automatically restore their post once they've selected a flair.
    * If the optional strict mode is enabled, Artemis will continue checking the post for flair updates for up to 24 hours. The post is considered completely abandoned if its submitter has not assigned it a flair within a day.

Artemis will not act upon unflaired posts by subreddit moderators.

### Statistics

**Artemis gathers various useful statistics on your community** and updates them at midnight UTC to the subreddit wiki at `r/SUBREDDIT/wiki/assistantbot_statistics`. These statistics are by default visible only to moderators, but moderators can choose to make the wiki page public and share it with their community.

#### Post Statistics

Artemis will provide you with information about the number of posts your subreddit receives and their flairs. That information is gathered and saved in a statistics page, organized by month for ease of viewing (newest first). It will also provide the total number of posts your subreddit receives per month. Note that the post flair that's saved is the flair *text* itself, not its CSS code.

Artemis also incorporates data from u/Stuck_In_the_Matrix's Pushshift data  for statistics (check it out at r/Pushshift). This data is used to retrieve data on the most frequent submitters and commenters to your subreddit each month, as well as provide aggregate statistics on how many daily submissions and comments your community receives per month.

###### Example for 2018-10

###### Submissions Activity

**Most Active Days**

* **27** submissions on **2018-10-04**
* **26** submissions on **2018-10-08**
* **24** submissions on **2018-10-23**

*Average submissions per day*: **18.44** submissions.

###### Comments Activity

**Most Active Days**

* **189** comments on **2018-10-04**
* **186** comments on **2018-10-10**
* **182** comments on **2018-10-14**

*Average comments per day*: **139.64** comments.

| Post Flair | Number of Posts | Percentage |
|------------|-----------------|------------|
| Culture | 3 | 1.14% |
| Discussion | 79 | 29.92% |
| Grammar | 9 | 3.41% |
| Historical | 2 | 0.76% |
| Media | 15 | 5.68% |
| None | 103 | 39.02% |
| Resources | 15 | 5.68% |
| Studying | 17 | 6.44% |
| Translation | 5 | 1.89% |
| Vocabulary | 16 | 6.06% |
| **Total** | 264 | 100% |

^(Example from r/ChineseLanguage)

#### Subscriber Statistics

Want to keep track of how your community has grown? Artemis will record the *net number of new subscribers* your subreddit receives every day. Reddit's traffic tables only records the raw number of *new* subscribers; their bar graph accounts for unsubscribers. Artemis will also calculate the net average daily subscriptions.

It's not a complete replacement for the now-defunct [RedditMetrics](http://redditmetrics.com) in that Artemis doesn't have generated charts, but it should give you an idea of how your community has grown (or heaven forbid, shrunk) over time.

###### Example 

* *Average Daily Change*: +9.5 subscribers

| Date | Subscribers | Change |
|------|-------------|--------|
| 2018-11-06 | 2606 | +19 |
| 2018-11-05 | 2587 | +14 |
| 2018-11-04 | 2573 | +4 |
| 2018-11-03 | 2569 | +15 |
| 2018-11-02 | 2554 | --- |

#### Traffic Statistics

Most moderators probably know that Reddit only keeps the last eleven months of traffic data on your subreddit `traffic` page plus the current month. This makes it difficult to keep track of how your subreddit has grown, over a period longer than a year, unless you store the data an external spreadsheet or something similar. 

Artemis will keep track of these traffic entries for you and add them to its statistics page as a table with the monthly uniques and pageviews. It will *also* calculate the percentage change in uniques and pageviews from the previous month, and also calculate the estimated traffic for the current month based on the traffic so far.

###### Example 

* *Average Uniques*: 14828.91
* *Average Pageviews*: 227819.82
* *Average Monthly Uniques Change*: 51.43%
* *Average Monthly Pageviews Change*: 50.47%

| Month | Uniques | Uniques % Change | Pageviews | Pageviews % Change |
|-------|---------|------------------|-----------|--------------------|
| 2018-10 | 42632 | *78.17%* | 668894 | *41.39%* |
| 2018-09 | 23928 | *-10.83%* | 473084 | *9.21%* |
| 2018-08 | 26833 | *22.45%* | 433170 | *48.56%* |
| 2018-07 | 21914 | *45.82%* | 291572 | *46.41%* |
| 2018-06 | 15028 | *44.07%* | 199149 | *72.38%* |

^(Example from r/Choices)

## I want u/AssistantBOT to assist my subreddit!

**Simply add u/AssistantBOT as a moderator to your subreddit.** It is that easy, and Artemis does not require more than [one or two permissions](https://www.reddit.com/r/modhelp/wiki/mod_permissions#wiki_moderator_permissions). Note:

* `(default mode)` If you just want Artemis to provide statistics information and *remind* OPs but **not** remove unflaired posts, invite it with `wiki` permissions. 
* `(optional strict mode)` If you'd like Artemis to proactively **remove posts that do not have a flair until their author selects one**, invite it with the `wiki` *and* the  `posts` permissions. 

Artemis will get to work once it accepts your moderator invite and will generate the first statistics page at midnight UTC. 


#### Settings

Artemis is explicitly designed to be easy-to-use and consequently doesn't really have "settings" apart from the moderator permissions noted above.

Moderators *can* choose to **turn off the default flair enforcing** if they want, retaining only Artemis's statistics-gathering function.

* To *disable flair enforcing*, moderators can send u/AssistantBOT a *modmail message* [from their subreddit](https://mod.reddit.com/mail/create) with `Disable` in the subject. Flair enforcing can be turned on again by sending another message with `Enable` in the subject.
* To *disable Artemis completely* on your subreddit, simply remove it as a moderator. Artemis will stop flair enforcing and gathering/updating statistics for the community once it's removed.
* Note: Statistics recording cannot be turned off.

#### Data

All of the data that Artemis collects, except for an individual subreddit's traffic data, is publicly available through [Reddit's API](https://www.reddit.com/dev/api/) or through other data sources like [Pushshift](https://pushshift.io/). Posts and subscriber statistics are pulled once daily and traffic data is pulled every month. Unmodding u/AssistantBOT from a subreddit automatically terminates all statistics-gathering for the sub. You can find the source code for Artemis [here](https://github.com/kungming2/AssistantBOT).

###### About Me

I'm the writer and maintainer of u/translator-BOT (Wenyuan and Ziwen) and u/LEGO_IDEAS_BOT. My bot Wenyuan has been keeping [detailed statistics](https://www.reddit.com/r/translator/wiki/overall_statistics) for r/translator for the last 2.5 years. I wanted to write a new statistics bot for some of the other communities that I moderate and decided to make it usable by other moderators as well. Please feel free to comment below if you have any questions about Artemis or its operations!

##### Credits

* u/Stuck_In_the_Matrix for his great work in operating and maintaining Pushshift.
* u/CWinthrop for letting Artemis's beta run on r/alcohol.