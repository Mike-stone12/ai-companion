# Memory benchmark: llm

| Run | |
| --- | --- |
| extractor | llm |
| started | 2026-10-15T00:09:13 |
| cases | cases.jsonl (93 cases) |
| gated_only | False |
| model | deepseek-flash |
| base_url | https://api.deepseek.com/v1 |
| rescored_from | eval/memory/results/2026-10-15-llm-deepseek-flash.jsonl |

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

## Pipeline (gate + llm extractor, what the app stores)

| Metric | Value |
| --- | --- |
| Precision (extracted summaries that match an expected fact) | 34/34 (100%) |
| Recall (expected facts found in some summary) | 36/81 (44%) |
| F1 | 0.62 |
| Noise on chit-chat (summaries for messages with nothing to remember) | 0 |

| Group | Cases | Expected facts | Recalled | Recall | Extracted | Correct | Precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| identity | 12 | 18 | 8 | 44% | 6 | 6 | 100% |
| preference | 12 | 12 | 4 | 33% | 4 | 4 | 100% |
| plan | 10 | 10 | 8 | 80% | 8 | 8 | 100% |
| event | 12 | 12 | 2 | 17% | 2 | 2 | 100% |
| relation | 6 | 7 | 6 | 86% | 5 | 5 | 100% |
| chitchat | 19 | 0 | 0 | n/a | 0 | 0 | n/a |
| paraphrase | 12 | 12 | 4 | 33% | 5 | 5 | 100% |
| conflict | 10 | 10 | 4 | 40% | 4 | 4 | 100% |
| lang=zh | 80 | 67 | 36 | 54% | 34 | 34 | 100% |
| lang=en | 13 | 14 | 0 | 0% | 0 | 0 | n/a |

| Case | Message | Missed facts | Extracted summaries |
| --- | --- | --- | --- |
| `identity-03` | 我今年24岁，刚毕业一年 | 用户24岁; 用户毕业一年 | (nothing) |
| `identity-07` | 我养了一只橘猫，叫团子 | 用户养了橘猫团子 | (nothing) |
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
| `plan-06` | 我计划国庆去日本玩一周 | 用户计划国庆去日本 | (nothing) |
| `plan-10` | I'm planning to run a half marathon in November. | half marathon in November | (nothing) |
| `event-01` | 我拿到字节的 offer 了！！！ | 用户拿到字节offer | (nothing) |
| `event-02` | 我被浙大录取了，九月去读研 | 用户被浙大录取 | (nothing) |
| `event-03` | 我今天正式入职了，新公司在滨江 | 用户今天入职新公司 | (nothing) |
| `event-05` | 我们上周领证了！ | 用户上周领证结婚 | (nothing) |
| `event-06` | 驾照考过了，终于 | 用户考过驾照 | (nothing) |
| `event-07` | 我上个月搬到深圳了 | 用户搬到深圳 | (nothing) |
| `event-08` | 我升职了，现在是组长 | 用户升职为组长 | (nothing) |
| `event-09` | 我刚做完阑尾炎手术，还在恢复 | 用户刚做了阑尾炎手术 | (nothing) |
| `event-11` | I got accepted into the master's program at NUS! | accepted into NUS master's | (nothing) |
| `event-12` | I just adopted a puppy named Mochi. | adopted puppy Mochi | (nothing) |
| `relation-05` | 我女儿今年上小学一年级了 | 用户女儿上小学一年级 | (nothing) |
| `paraphrase-02` | 早上没咖啡我整个人都不行，太爱咖啡了 | 用户喜欢咖啡 | (nothing) |
| `paraphrase-03` | 我真的是咖啡重度爱好者 | 用户喜欢咖啡 | (nothing) |
| `paraphrase-05` | 对了，再说一遍，我的名字是小林哦 | 用户名叫小林 | (nothing) |
| `paraphrase-06` | 我家有只猫叫团子，特别黏人 | 用户的猫叫团子 | (nothing) |
| `paraphrase-07` | 团子今天又在我键盘上睡觉，我家猫真的 | 用户的猫叫团子 | (nothing) |
| `paraphrase-08` | 我的猫团子是只橘猫 | 用户的猫叫团子 | (nothing) |
| `paraphrase-11` | I live in Hangzhou now. | user lives in Hangzhou | (nothing) |
| `paraphrase-12` | Hangzhou, where I live, is really humid in summer. | user lives in Hangzhou | (nothing) |
| `conflict-02` | 我上个月搬到上海了，现在住在浦东 | 用户住在上海浦东 | (nothing) |
| `conflict-04` | 我上周离职了，现在在一家创业公司做运营 | 用户在创业公司做运营 | (nothing) |
| `conflict-06` | 我现在戒奶茶了，改喝无糖茶 | 用户戒了奶茶改喝无糖茶 | (nothing) |
| `conflict-08` | 我和阿凯分手了，现在单身 | 用户和阿凯分手了 | (nothing) |
| `conflict-09` | I'm working at Tencent as a PM. | user works at Tencent | (nothing) |
| `conflict-10` | I left Tencent last month and joined a startup. | user left Tencent for a startup | (nothing) |

## Extractor alone (llm on every message, gate ignored)

| Metric | Value |
| --- | --- |
| Precision (extracted summaries that match an expected fact) | 76/77 (99%) |
| Recall (expected facts found in some summary) | 81/81 (100%) |
| F1 | 0.99 |
| Noise on chit-chat (summaries for messages with nothing to remember) | 0 |

| Group | Cases | Expected facts | Recalled | Recall | Extracted | Correct | Precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| identity | 12 | 18 | 18 | 100% | 13 | 13 | 100% |
| preference | 12 | 12 | 12 | 100% | 12 | 12 | 100% |
| plan | 10 | 10 | 10 | 100% | 10 | 10 | 100% |
| event | 12 | 12 | 12 | 100% | 13 | 12 | 92% |
| relation | 6 | 7 | 7 | 100% | 6 | 6 | 100% |
| chitchat | 19 | 0 | 0 | n/a | 0 | 0 | n/a |
| paraphrase | 12 | 12 | 12 | 100% | 13 | 13 | 100% |
| conflict | 10 | 10 | 10 | 100% | 10 | 10 | 100% |
| lang=zh | 80 | 67 | 67 | 100% | 65 | 64 | 98% |
| lang=en | 13 | 14 | 14 | 100% | 12 | 12 | 100% |

## Store after scenario turns (pipeline)

| Scenario | Group | Stored | Duplicates | Stale | Missing | Entries |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| dup-coffee | paraphrase | 1 | 0 | 0 | 0/1 | 用户喜欢喝咖啡，每天早上一杯 |
| dup-name | paraphrase | 1 | 0 | 0 | 0/1 | 用户名叫小林 |
| dup-cat | paraphrase | 0 | 0 | 0 | 1/1 | (empty) |
| dup-job | paraphrase | 3 | 2 | 0 | 0/1 | 用户在游戏公司做后端; 用户在游戏公司工作; 近期赶版本，后端常加班 |
| dup-en | paraphrase | 0 | 0 | 0 | 1/1 | (empty) |
| upd-city | conflict | 1 | 0 | 1 | 1/1 | 用户住在杭州西湖区 |
| upd-job | conflict | 1 | 0 | 1 | 1/1 | 用户在外企从事市场工作 |
| upd-drink | conflict | 1 | 0 | 1 | 1/1 | 用户爱喝奶茶，每天一杯 |
| upd-relationship | conflict | 1 | 0 | 1 | 1/1 | 用户有男朋友叫阿凯 |
| upd-en | conflict | 0 | 0 | 0 | 1/1 | (empty) |

| Metric | Value |
| --- | --- |
| Stored entries | 9 |
| Duplicate rate (entries that repeat a fact already stored) | 2/9 (22%) |
| Stale rate (entries a later message contradicted) | 4/9 (44%) |
| Current facts missing from the store | 7/10 |

## Store after scenario turns (extractor alone)

| Scenario | Group | Stored | Duplicates | Stale | Missing | Entries |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| dup-coffee | paraphrase | 3 | 2 | 0 | 0/1 | 用户喜欢喝咖啡，每天早上一杯; 用户非常爱喝咖啡; 用户是咖啡重度爱好者 |
| dup-name | paraphrase | 2 | 1 | 0 | 0/1 | 用户名叫小林; 用户名字是小林 |
| dup-cat | paraphrase | 3 | 2 | 0 | 0/1 | 用户养猫叫团子，性格黏人; 用户养了一只叫团子的猫; 用户养橘猫叫团子 |
| dup-job | paraphrase | 3 | 2 | 0 | 0/1 | 用户在游戏公司做后端; 用户在游戏公司工作; 近期赶版本，后端常加班 |
| dup-en | paraphrase | 2 | 1 | 0 | 0/1 | 用户现居杭州; 用户居住在杭州 |
| upd-city | conflict | 2 | 0 | 1 | 0/1 | 用户住在杭州西湖区; 用户上个月搬到上海浦东居住 |
| upd-job | conflict | 2 | 0 | 1 | 0/1 | 用户在外企从事市场工作; 用户上周离职，现于创业公司做运营 |
| upd-drink | conflict | 2 | 0 | 1 | 0/1 | 用户爱喝奶茶，每天一杯; 戒奶茶改喝无糖茶 |
| upd-relationship | conflict | 2 | 0 | 1 | 0/1 | 用户有男朋友叫阿凯; 用户与阿凯已分手，现单身 |
| upd-en | conflict | 2 | 0 | 1 | 0/1 | 用户在腾讯担任产品经理; 上月离开腾讯，加入创业公司 |

| Metric | Value |
| --- | --- |
| Stored entries | 23 |
| Duplicate rate (entries that repeat a fact already stored) | 8/23 (35%) |
| Stale rate (entries a later message contradicted) | 5/23 (22%) |
| Current facts missing from the store | 0/10 |
