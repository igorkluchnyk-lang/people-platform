# People Platform: HRM для маленької команди

Одна HTML-сторінка на claude.ai (приватний artifact з власною базою), яка веде людей команди: цілі (каскад компанія → напрям → людина, живі статуси з Linear), онбординг, 1:1 і брифи до них, тижневий і місячний синк одним сценарієм, follow-up після зустрічі однією кнопкою, пульс команди, 360, календар, база знань.

Походження: Chia People (people partner Ігор Ключник, вересень-листопад 2026). Тут тільки код, схема, інструменти і вигаданий приклад. Реальних людей, умов, переписок і ключів немає.

## Як перенести у свій проєкт (5 хвилин)

1. Натисни **Use this template** (або Fork) угорі цієї сторінки, або просто скопіюй посилання на репозиторій.
2. Відкрий Claude Code у папці свого проєкту (desktop або CLI, з увімкненими Artifacts).
3. Встав промпт:

```
Розгорни People Platform для моєї команди з https://github.com/igorkluchnyk-lang/people-platform .
Прочитай README.md і CONTRIBUTING.md. Потім:
1) спитай мене про команду: хто є хто (імʼя, роль, старт, лід), ціль компанії і метрика, напрями, цілі людей на цей місяць, ритм зустрічей, канали Slack;
2) збери seed/ за схемою з README, заповни ORDER і CFG у platform.html, заміни бренд (назва, кольори);
3) опублікуй platform.html як приватний Artifact з можливостями db, user, sample, mcp (за README), запиши seed через ArtifactData batch;
4) перевір дашборд, «Цілі», одну людину, «Тижневий синк» і дай мені посилання.
Нічого не відправляй людям без мого «так».
```

4. Відкрий посилання, перевір, поділись з CEO через Share (Contributor).

Конектори, які варто мати в claude.ai: Linear (живі цілі), Pocket або Granola (записи 1:1), Slack і Gmail (бриф). Без конектора відповідна функція просто вимикається.

## Що всередині

| Шлях | Що це |
|---|---|
| `platform.html` | сторінка платформи (vanilla JS, без збірки), v38 |
| `live_overlay.js` | живий шар окремо: `liveApply(L)` накладає статуси з Linear на цілі, `liveBadge()` (вбудований і в `platform.html`) |
| `vercel/` | read-only копія для людей без claude.ai: `build.py`, сторінка з паролем, `api/live.js` (Linear + Slack) |
| `scripts/goals_daily.py` | щоденний тред у Slack-каналі цілей: по людині N/M done, наступна, прострочені (без LLM, для cron) |
| `scripts/pulse_watch.py` | сторож пульсу: на кожну відповідь Google-форми повідомлення партнеру в Telegram, після дедлайну хто не відповів (без LLM, для cron) |
| `tools/build_batches.py` | папка `seed/<колекція>/<id>.json` → батчі для ArtifactData по 50 записів |
| `seed_example/` | вигадана команда з 2 людей: ціль компанії → напрям → ціль людини, онбординг, питання, репорт, пульс |

## Сторінки

- **Дашборд**: ціль компанії і напрями, онбординг нових людей, черга 1:1 → цілі, пульс, тиждень.
- **Цілі**: смуга цілі компанії, рядок на людину з крапками 🟢🟡🔴⬜, «чому такий статус», цілі по місяцях, черга «на підтвердження».
- **Людина**: огляд з брифом до 1:1 (кнопка збирає Slack, пошту, зустрічі), follow-up після зустрічі, цілі і репорти, зустрічі, питання, документи і доступи, 360, фінал initial term.
- **Тижневий синк** і **Місячний синк**: сценарій з бази, текст у чат, блок партнера редагується, повідомлення в Slack до дзвінка, follow-up після з перевіркою нікнеймів.
- **Календар**, **Вхідні**, **Як ми працюємо** (база знань, ритм, банк питань для 1:1).

## Розгортання вручну (для сесії Claude Code)

1. Скопіюй `platform.html` у свій проєкт і зміни під команду (розділ «Що змінити» нижче).
2. Опублікуй її як Artifact з можливостями:
   - `db`, правила: корінь `read: interact`, `write: admin`; колекції `questions`, `notes`, `access`, `surveys` і `data/users/{self}`: `write: interact`;
   - `user` зі scope `profile`;
   - `sample` (бриф, 360, розбір 1:1 → цілі, адженда, follow-up);
   - `mcp`: `Linear` [`list_issues`], `Pocket` [`search_pocket_conversations`], `Granola` [`search_meetings`, `get_meetings`], `Slack` [`slack_search_public_and_private`], `Gmail` [`search_threads`].
   Перед публікацією завантаж скіл `artifact-capabilities`.
3. Збери дані в `seed/` за схемою нижче, `python3 tools/build_batches.py seed out/`, кожен `out/batch_N.json` через `ArtifactData` action `batch`.
4. Відкрий artifact, перевір дашборд, «Цілі», одну людину, «Тижневий синк».

## Живий шар: що оновлюється само

1. **Цілі з Linear при відкритті.** Конвенція: на кожну людину і місяць батьківська задача `<Name>'s <Month> goals` (напр. `Anna's November goals`), цілі місяця = її дочірні задачі (`Anna Nov goal 1: …`, дата = дедлайн). Сторінка знаходить їх (`list_issues`, останні 120 днів), бере статус (`completed` → виконано, `canceled` → знято, «review» → чекає, прострочено → відстає, ≤3 дні і не почато → ризик), пише зміни в базу (`goals`: status, live, doneAt, due), нові цілі місяця створює як `goals/lin-<ID>`, цілі минулого місяця позначає `archived:true` і ховає. Виконане з минулого візиту підсвічується «✓ нове». Пише тільки редактор; у інших зміни видно лише в їхньому вікні.
2. **1:1 → цілі.** Раз на 4 години при відкритті (або кнопкою «Розібрати зараз» на дашборді) сторінка бере нові записи з Pocket і Granola з моменту останньої синхронізації (`sync/meetings`), лишає ті, де згадано людей команди (імена в `NMS`), і Claude (`sample`) витягує по кожній цілі рішення, статус і нову дату. Пише `meetings/<pocket|granola>-<id>` і нотатку цілі; статус і дату міняє тільки для цілей без Linear (Linear головний). Нові цілі приходять як `approved:false` «на погодженні».
3. **Бриф кнопкою** лишається ручним: збирає Slack, пошту, Granola, Pocket і базу.
4. **Vercel-копія** тягне `/api/live` кожні 5 хвилин (ті самі цілі з Linear плюс цифри компанії з ранкового поста бота в Slack, якщо є `GOALS_CHANNEL`).

## Розгортання на Vercel (необовʼязково)

1. `cd vercel && python3 build.py ../seed` → `site/index.html` (дані вшиті, без запису).
2. `cd site && npx vercel deploy --prod`. Env у Vercel: `SITE_PASSWORD` (вхід), `LINEAR_API_KEY`, необовʼязково `SLACK_TOKEN` + `GOALS_CHANNEL` (ID каналу з ранковим постом виду «*N* of M active patients»), `PEOPLE_MAP` JSON, якщо перше слово в назві цілей не збігається з key людини.
3. `scripts/goals_daily.py` для cron: env `LINEAR_API_KEY`, `SLACK_TOKEN`, `GOALS_CHANNEL`, `NAMES_MAP` JSON (key → імʼя в Slack). Спершу сухий прогін, потім cron, напр. `5 15 * * 1-5` UTC.

## Що змінити під іншу команду

1. На початку скрипта: `const ORDER=[]` (ключі людей у порядку показу) і `CFG`: `dmChannel` (Slack ID DM партнера з CEO для брифу, порожньо = не шукати), `target` і `unit` (ціль компанії за замовчуванням, напр. 100 «клієнтів»), `goalsChannel` і `teamChannel` (канали Slack для цілей і команди).
2. Імена для пошуку в записах: `NM` (follow-up) і `NMS` (1:1 → цілі), `ENN` (англійські імена у сценарії monthly), `MALE` (рід), `LPEOPLE` (перше слово назви цілей у Linear → key). Нік у Slack для follow-up: поле `slack` у `people/<key>` (напр. `"@Anna Example"`); `NICKFIX` опційно виправляє короткі імена на точні ніки.
3. Ролі: людина з key `ceo` = лід, `partner` = people partner (сторінка партнера показує адженду синку з CEO). У текстах стоїть «CEO» і «партнер»; питання до ліда мають `to: "CEO"`. Назви полів `needFromVitalik` і `vitalik` (бриф для CEO) лишились зі схеми Chia People, їх не перейменовуй без міграції бази.
4. Бренд: кольори в `:root`, SVG-логотип у шапці, шрифти.
5. Тексти під ваш процес: правила 360 і рубрика дня Х (`tReview`), «Опитувальник через місяць» (`MS`), підказки для брифу і 360 (`genBrief`, `genSurvey`).
6. Ціль компанії задається документом `goals/co-1` (`level: "company"`), напрями `goals/dir-*` (`level: "direction"`, `owner`, `parent: "co-1"`), цілі людей мають `person` і `parent`.

## Схема бази

| Колекція | Ключові поля |
|---|---|
| `people` | key, name, short, role, slack, color (green/yellow/red), start, termEnd, lead, buddy, location, tz, window, summaryPoints[], signals[], about{}, d{} (профіль D1-D4), onboarding[] {step, date, status: done/now/next/risk/miss, note, links[]}, docsFolder, linkedin, links[], facts[], needFromVitalik |
| `goals` | Linear-поля: url, live, liveAt, doneAt, archived; компанія: level=company, owner, title, current, target, unit, due, status; напрям: level=direction, owner, parent; людина: person, parent, title, measure, current, target, unit, due, status (done/on_track/at_risk/behind/unknown), note, source, order |
| `reports` | person, date, goals[] {t, s: green/yellow/red, n}, progress[], next[], needed[], url |
| `meetings` | person або people[], date, kind, title, summary, agreed[], signals[], score, source |
| `questions` | person, text, to, status (open/answered/dropped), raisedAt, answer, closedAt |
| `agenda` | date, time, kind (one/team/checkpoint/term/sync/money/absence/plan), person, title, warn, note |
| `docs` | person, type, status (signed/sent/missing/unknown/pending), date, where, url, note |
| `access` | person, system, issued, works, by, note |
| `pay`, `comp` | виплати і умови (тільки для власника і CEO) |
| `hiring` | історія відбору (тільки читання): profile, scorecard, stages, references, ceoBrief, final |
| `prep` | бриф до зустрічі: tails, ask, goalsRisk, praise, avoid, after |
| `sync` | `sync/meetings`: lastAt, runAt, done[] (які записи вже розібрано) |
| `goalq` | черга «на підтвердження» з 1:1: kind (update/new), goal, person, текст; у `goals` пишеться тільки після ✓ |
| `msync` | сценарії синків: `msync/next` (місячний), `msync/weekly` (тижневий, блок партнера редагується) |
| `fups` | follow-up після зустрічі: analysis, message, vitalik (DM CEO), generatedAt, editedAt |
| `pulse` | пульс команди, документ = дата старту: title, start, deadline, form, roster[], responses[] {person, energy, clarity, blocker, at}, conclusions[] |
| `vsync` | адженда синку партнера з CEO (`vsync/next`) |
| `kb`, `rhythm`, `qbank` | база знань «Як ми працюємо», ритм команди, банк питань для 1:1 |
| `events`, `notes`, `inbox`, `surveys`, `company` | таймлайн, нотатки, вхідні агента, опитувальники 360, загальні цифри компанії |
| `data/users/<id>/red-<person>` | приватне власника (бачить тільки він) |

## Як рахується каскад

- Ціль компанії має свою метрику (current / target).
- Прогрес напряму: середнє по цілях людей під ним. Ціль з числом дає свій %, без числа: виконано 100, в графіку 60, ризик 35, відстає 10; невідомо не рахується.
- Стан напряму: половина і більше під ризиком або відстає → червоний; третина → жовтий; усе виконано → виконано.
- Напрям цілі змінюється на сторінці людини (вкладка «Цілі і репорти»), якщо в тебе права редактора.

## Відкат

Кожна публікація artifact зберігає версію: стару можна повернути з історії версій. Дані бази перед великими змінами варто знімати (`ArtifactData` list з `out_dir`) у папку `snapshots/<дата>/`.

## Версії

- v38 (09.11.2026): тижневий синк, follow-up однією кнопкою з перевіркою нікнеймів (поле `slack`), пульс команди (`pulse`, `pulse_watch.py`), цілі по місяцях, черга 1:1 → цілі з підтвердженням, адженда синку з CEO кнопкою, `CFG` замість захардкоджених цифр і каналів.
- v30 (05.11.2026): живий шар (Linear при відкритті, 1:1 → цілі з Pocket/Granola), Vercel `/api/live`, `goals_daily.py`.
- v4 (22.10.2026): перший шаблон (каскад цілей, онбординг, 1:1, 360).

Хочеш щось додати або виправити: `CONTRIBUTING.md`.

Ліцензія: MIT (`LICENSE`), можна брати й змінювати із зазначенням автора.
