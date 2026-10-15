# Memory benchmark: heuristic

| Run | |
| --- | --- |
| extractor | heuristic |
| started | 2026-10-14T23:43:34 |
| cases | cases.jsonl (93 cases) |
| gated_only | False |
| rescored_from | eval/memory/results/2026-10-14-heuristic.jsonl |

## Gate (rule-based, no API calls)

| Metric | Value |
| --- | --- |
| Cases | 93 (74 with something to remember) |
| Passed to the extractor | 40 |
| Gate recall (messages with facts that reach the extractor) | 33/74 (45%) |
| Gate precision (passed messages that hold a fact) | 33/40 (82%) |
| Missed (facts lost before extraction) | 41: `identity-03`, `identity-07`, `identity-09`, `identity-10`, `identity-11`, `identity-12`, `preference-02`, `preference-05`, `preference-06`, `preference-07`, `preference-08`, `preference-09`, `preference-11`, `preference-12`, `plan-06`, `plan-10`, `event-01`, `event-02`, `event-03`, `event-05`, `event-06`, `event-07`, `event-08`, `event-09`, `event-11`, `event-12`, `relation-05`, `paraphrase-02`, `paraphrase-03`, `paraphrase-05`, `paraphrase-06`, `paraphrase-07`, `paraphrase-08`, `paraphrase-11`, `paraphrase-12`, `conflict-02`, `conflict-04`, `conflict-06`, `conflict-08`, `conflict-09`, `conflict-10` |
| False alarms (chit-chat that costs a request) | 7: `chitchat-07`, `chitchat-08`, `chitchat-09`, `chitchat-10`, `chitchat-12`, `chitchat-14`, `chitchat-17` |

| Group | Cases | With facts | Passed | Missed | False alarms |
| --- | ---: | ---: | ---: | ---: | ---: |
| identity | 12 | 12 | 6 | 6 | 0 |
| preference | 12 | 12 | 4 | 8 | 0 |
| plan | 10 | 10 | 8 | 2 | 0 |
| event | 12 | 12 | 2 | 10 | 0 |
| relation | 6 | 6 | 5 | 1 | 0 |
| chitchat | 19 | 0 | 7 | 0 | 7 |
| paraphrase | 12 | 12 | 4 | 8 | 0 |
| conflict | 10 | 10 | 4 | 6 | 0 |
| lang=zh | 80 | 63 | 40 | 30 | 7 |
| lang=en | 13 | 11 | 0 | 11 | 0 |

## Pipeline (gate + heuristic extractor, what the app stores)

| Metric | Value |
| --- | --- |
| Precision (extracted summaries that match an expected fact) | 12/12 (100%) |
| Recall (expected facts found in some summary) | 12/81 (15%) |
| F1 | 0.26 |
| Noise on chit-chat (summaries for messages with nothing to remember) | 0 |

| Group | Cases | Expected facts | Recalled | Recall | Extracted | Correct | Precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| identity | 12 | 18 | 4 | 22% | 4 | 4 | 100% |
| preference | 12 | 12 | 4 | 33% | 4 | 4 | 100% |
| plan | 10 | 10 | 0 | 0% | 0 | 0 | n/a |
| event | 12 | 12 | 0 | 0% | 0 | 0 | n/a |
| relation | 6 | 7 | 0 | 0% | 0 | 0 | n/a |
| chitchat | 19 | 0 | 0 | n/a | 0 | 0 | n/a |
| paraphrase | 12 | 12 | 2 | 17% | 2 | 2 | 100% |
| conflict | 10 | 10 | 2 | 20% | 2 | 2 | 100% |
| lang=zh | 80 | 67 | 12 | 18% | 12 | 12 | 100% |
| lang=en | 13 | 14 | 0 | 0% | 0 | 0 | n/a |

| Case | Message | Missed facts | Extracted summaries |
| --- | --- | --- | --- |
| `identity-03` | 我今年24岁，刚毕业一年 | 用户24岁; 用户毕业一年 | (nothing) |
| `identity-04` | 我是一名大学生，在杭州读计算机 | 用户在杭州; 用户读计算机 | 用户身份：一名大学生 |
| `identity-06` | 我在一家游戏公司做后端开发 | 用户在游戏公司做后端开发 | (nothing) |
| `identity-07` | 我养了一只橘猫，叫团子 | 用户养了橘猫团子 | (nothing) |
| `identity-08` | 我的生日是5月3号 | 用户生日5月3日 | (nothing) |
| `identity-09` | 我老家在东北，哈尔滨的 | 用户老家哈尔滨 | (nothing) |
| `identity-10` | 我对花生过敏，吃了会起疹子 | 用户花生过敏 | (nothing) |
| `identity-11` | My name is Lin and I'm a software engineer in Shenzhen. | user is called Lin; software engineer; in Shenzhen | (nothing) |
| `identity-12` | I'm 27 and I just moved to Chengdu for work. | user is 27; moved to Chengdu | (nothing) |
| `preference-02` | 我特别喜欢周杰伦的歌，尤其是早期的专辑 | 用户喜欢周杰伦 | (nothing) |
| `preference-05` | 我不吃辣，一点都不能吃 | 用户不吃辣 | (nothing) |
| `preference-06` | 我最爱的电影是《星际穿越》，看了五遍 | 用户最爱电影星际穿越 | (nothing) |
| `preference-07` | 我习惯晚上十二点以后才睡，早上起不来 | 用户习惯晚睡 | (nothing) |
| `preference-08` | 我平时喜欢打羽毛球，一周打两次 | 用户喜欢打羽毛球 | (nothing) |
| `preference-09` | 我受不了别人大声说话 | 用户不喜欢别人大声说话 | (nothing) |
| `preference-11` | I love spicy food, especially Sichuan hotpot. | user loves spicy food / hotpot | (nothing) |
| `preference-12` | I really don't like coffee, I'm more of a tea person. | user prefers tea, dislikes coffee | (nothing) |
| `plan-01` | 我下周三要去北京面试，有点紧张 | 用户下周三去北京面试 | (nothing) |
| `plan-02` | 我打算明年考研，准备考北大的计算机 | 用户打算考研 | (nothing) |
| `plan-03` | 我准备下个月开始学吉他 | 用户准备学吉他 | (nothing) |
| `plan-04` | 周末我要去爬山，和几个朋友一起 | 用户周末去爬山 | (nothing) |
| `plan-05` | 明天早上八点有个很重要的会，别让我睡过头 | 用户明天八点开会 | (nothing) |
| `plan-06` | 我计划国庆去日本玩一周 | 用户计划国庆去日本 | (nothing) |
| `plan-07` | 下周末是我妈生日，我得记得买礼物 | 用户妈妈下周末生日 | (nothing) |
| `plan-08` | 我打算把这份工作辞了，太累了 | 用户打算辞职 | (nothing) |
| `plan-09` | 过两天要搬家，东西好多 | 用户要搬家 | (nothing) |
| `plan-10` | I'm planning to run a half marathon in November. | half marathon in November | (nothing) |
| `event-01` | 我拿到字节的 offer 了！！！ | 用户拿到字节offer | (nothing) |
| `event-02` | 我被浙大录取了，九月去读研 | 用户被浙大录取 | (nothing) |
| `event-03` | 我今天正式入职了，新公司在滨江 | 用户今天入职新公司 | (nothing) |
| `event-04` | 我昨天跟男朋友分手了 | 用户和男朋友分手 | (nothing) |
| `event-05` | 我们上周领证了！ | 用户上周领证结婚 | (nothing) |
| `event-06` | 驾照考过了，终于 | 用户考过驾照 | (nothing) |
| `event-07` | 我上个月搬到深圳了 | 用户搬到深圳 | (nothing) |
| `event-08` | 我升职了，现在是组长 | 用户升职为组长 | (nothing) |
| `event-09` | 我刚做完阑尾炎手术，还在恢复 | 用户刚做了阑尾炎手术 | (nothing) |
| `event-10` | 我最近换了新工作，在一家做 AI 的创业公司 | 用户换了工作，在AI创业公司 | (nothing) |
| `event-11` | I got accepted into the master's program at NUS! | accepted into NUS master's | (nothing) |
| `event-12` | I just adopted a puppy named Mochi. | adopted puppy Mochi | (nothing) |
| `relation-01` | 我男朋友叫阿凯，我们在一起三年了 | 用户男朋友叫阿凯; 在一起三年 | (nothing) |
| `relation-02` | 我妈最近身体不太好，血压有点高 | 用户妈妈血压高 | (nothing) |
| `relation-03` | 我室友是个夜猫子，每天打游戏到两点 | 用户室友晚睡打游戏 | (nothing) |
| `relation-04` | 我有个姐姐在加拿大，经常视频 | 用户姐姐在加拿大 | (nothing) |
| `relation-05` | 我女儿今年上小学一年级了 | 用户女儿上小学一年级 | (nothing) |
| `relation-06` | 我和同事小王关系很好，经常一起吃饭 | 用户和同事小王关系好 | (nothing) |
| `paraphrase-02` | 早上没咖啡我整个人都不行，太爱咖啡了 | 用户喜欢咖啡 | (nothing) |
| `paraphrase-03` | 我真的是咖啡重度爱好者 | 用户喜欢咖啡 | (nothing) |
| `paraphrase-05` | 对了，再说一遍，我的名字是小林哦 | 用户名叫小林 | (nothing) |
| `paraphrase-06` | 我家有只猫叫团子，特别黏人 | 用户的猫叫团子 | (nothing) |
| `paraphrase-07` | 团子今天又在我键盘上睡觉，我家猫真的 | 用户的猫叫团子 | (nothing) |
| `paraphrase-08` | 我的猫团子是只橘猫 | 用户的猫叫团子 | (nothing) |
| `paraphrase-09` | 我在一家游戏公司上班，做后端 | 用户在游戏公司做后端 | (nothing) |
| `paraphrase-10` | 我们游戏公司最近在赶版本，后端天天加班 | 用户在游戏公司做后端 | (nothing) |
| `paraphrase-11` | I live in Hangzhou now. | user lives in Hangzhou | (nothing) |
| `paraphrase-12` | Hangzhou, where I live, is really humid in summer. | user lives in Hangzhou | (nothing) |
| `conflict-02` | 我上个月搬到上海了，现在住在浦东 | 用户住在上海浦东 | (nothing) |
| `conflict-03` | 我在一家外企做市场 | 用户在外企做市场 | (nothing) |
| `conflict-04` | 我上周离职了，现在在一家创业公司做运营 | 用户在创业公司做运营 | (nothing) |
| `conflict-06` | 我现在戒奶茶了，改喝无糖茶 | 用户戒了奶茶改喝无糖茶 | (nothing) |
| `conflict-07` | 我有个男朋友叫阿凯 | 用户男朋友叫阿凯 | (nothing) |
| `conflict-08` | 我和阿凯分手了，现在单身 | 用户和阿凯分手了 | (nothing) |
| `conflict-09` | I'm working at Tencent as a PM. | user works at Tencent | (nothing) |
| `conflict-10` | I left Tencent last month and joined a startup. | user left Tencent for a startup | (nothing) |

## Extractor alone (heuristic on every message, gate ignored)

| Metric | Value |
| --- | --- |
| Precision (extracted summaries that match an expected fact) | 12/12 (100%) |
| Recall (expected facts found in some summary) | 12/81 (15%) |
| F1 | 0.26 |
| Noise on chit-chat (summaries for messages with nothing to remember) | 0 |

| Group | Cases | Expected facts | Recalled | Recall | Extracted | Correct | Precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| identity | 12 | 18 | 4 | 22% | 4 | 4 | 100% |
| preference | 12 | 12 | 4 | 33% | 4 | 4 | 100% |
| plan | 10 | 10 | 0 | 0% | 0 | 0 | n/a |
| event | 12 | 12 | 0 | 0% | 0 | 0 | n/a |
| relation | 6 | 7 | 0 | 0% | 0 | 0 | n/a |
| chitchat | 19 | 0 | 0 | n/a | 0 | 0 | n/a |
| paraphrase | 12 | 12 | 2 | 17% | 2 | 2 | 100% |
| conflict | 10 | 10 | 2 | 20% | 2 | 2 | 100% |
| lang=zh | 80 | 67 | 12 | 18% | 12 | 12 | 100% |
| lang=en | 13 | 14 | 0 | 0% | 0 | 0 | n/a |

## Store after scenario turns (pipeline)

| Scenario | Group | Stored | Duplicates | Stale | Missing | Entries |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| dup-coffee | paraphrase | 1 | 0 | 0 | 0/1 | 用户喜欢：喝咖啡 |
| dup-name | paraphrase | 1 | 0 | 0 | 0/1 | 用户名字：小林 |
| dup-cat | paraphrase | 0 | 0 | 0 | 1/1 | (empty) |
| dup-job | paraphrase | 0 | 0 | 0 | 1/1 | (empty) |
| dup-en | paraphrase | 0 | 0 | 0 | 1/1 | (empty) |
| upd-city | conflict | 1 | 0 | 1 | 1/1 | 用户住在：杭州 |
| upd-job | conflict | 0 | 0 | 0 | 1/1 | (empty) |
| upd-drink | conflict | 1 | 0 | 1 | 1/1 | 用户喜欢：喝奶茶 |
| upd-relationship | conflict | 0 | 0 | 0 | 1/1 | (empty) |
| upd-en | conflict | 0 | 0 | 0 | 1/1 | (empty) |

| Metric | Value |
| --- | --- |
| Stored entries | 4 |
| Duplicate rate (entries that repeat a fact already stored) | 0/4 (0%) |
| Stale rate (entries a later message contradicted) | 2/4 (50%) |
| Current facts missing from the store | 8/10 |

## Store after scenario turns (extractor alone)

| Scenario | Group | Stored | Duplicates | Stale | Missing | Entries |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| dup-coffee | paraphrase | 1 | 0 | 0 | 0/1 | 用户喜欢：喝咖啡 |
| dup-name | paraphrase | 1 | 0 | 0 | 0/1 | 用户名字：小林 |
| dup-cat | paraphrase | 0 | 0 | 0 | 1/1 | (empty) |
| dup-job | paraphrase | 0 | 0 | 0 | 1/1 | (empty) |
| dup-en | paraphrase | 0 | 0 | 0 | 1/1 | (empty) |
| upd-city | conflict | 1 | 0 | 1 | 1/1 | 用户住在：杭州 |
| upd-job | conflict | 0 | 0 | 0 | 1/1 | (empty) |
| upd-drink | conflict | 1 | 0 | 1 | 1/1 | 用户喜欢：喝奶茶 |
| upd-relationship | conflict | 0 | 0 | 0 | 1/1 | (empty) |
| upd-en | conflict | 0 | 0 | 0 | 1/1 | (empty) |

| Metric | Value |
| --- | --- |
| Stored entries | 4 |
| Duplicate rate (entries that repeat a fact already stored) | 0/4 (0%) |
| Stale rate (entries a later message contradicted) | 2/4 (50%) |
| Current facts missing from the store | 8/10 |
