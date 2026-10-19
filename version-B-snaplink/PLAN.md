<div dir="rtl">

# 🗺️ PLAN.md — نقشه‌ی راه ۳ ساعته · نسخه‌ی B: SnapLink

> این فایل را در **ریشه‌ی ریپازیتوری** خودت بگذار. بخش «تصمیم‌های من» را در مرحله‌ی ۰ پر کن و در پایان جدول خودارزیابی را کامل کن.

---

## 🧭 چطور از این نقشه استفاده کنی

هر مرحله این بخش‌ها را دارد:

| نشانه | معنی |
|---|---|
| ⏱️ | زمان پیشنهادی (ساعت آزمون، از ۰:۰۰ تا ۳:۰۰) |
| 🎯 | هدف مرحله |
| ✅ | کارهایی که باید انجام بدهی |
| 🏁 | «تمام است وقتی…»: چطور بفهمی مرحله واقعاً تمام شده |
| 💯 | امتیازها؛ مدرس هم دقیقاً با همین چک‌باکس‌ها نمره می‌دهد |
| 💡 | نکته‌ها و راهنمایی |
| 🤖 | تله‌های هوش مصنوعی: اشتباه‌هایی که AI زیاد می‌کند و امتیاز تو را می‌گیرد |
| 🚩 | نقطه‌ی بازرسی: کامیت و ادغام (merge) |

**چهار قانون طلایی:**

1. **اول کار کند، بعد زیبا شود.** نسخه‌ی ساده‌ای که کار می‌کند از نسخه‌ی کامل نیمه‌کاره بهتر است.
2. **گیر نکن.** امتیاز جزئی همه‌جا هست. اگر بیش از ۱۰ دقیقه روی یک مشکل ماندی، آن را در README یادداشت کن و برو مرحله‌ی بعد.
3. **سراغ امتیاز اضافه فقط وقتی برو که** همه‌ی مراحل اصلی تمام شده باشد. (این یک توصیه است؛ امتیاز اضافه در هر حال شمرده می‌شود و در رسیدن به نمره‌ی قبولی هم حساب است.)
4. **هر کدی که AI به تو داد، اجرا کن و بفهم.** سؤال‌های دفاع از همین کدها پرسیده می‌شود.

---

## ⏱️ جدول زمان‌بندی

| زمان | مرحله | امتیاز | شاخه (branch) |
|---|---|---|---|
| ۰:۰۰ تا ۰:۱۰ | S0 شروع و «تصمیم‌های من» | ۵ | `main` |
| ۰:۱۰ تا ۱:۰۵ | S1 برنامه‌ی Go | ۲۵ | `feat/api` |
| ۱:۰۵ تا ۱:۲۰ | S2 تست‌ها | ۸ | `test/unit` |
| ۱:۲۰ تا ۱:۳۵ | S3 لینوکس و Bash | ۷ | `chore/scripts` |
| ۱:۳۵ تا ۱:۵۵ | S4 Docker | ۹ | `build/docker` |
| ۱:۵۵ تا ۲:۱۰ | S5 Docker Compose | ۷ | `build/compose` |
| ۲:۱۰ تا ۲:۲۵ | S6 CI با GitHub Actions | ۶ | `ci/github-actions` |
| ۲:۲۵ تا ۲:۵۰ | S7 Kubernetes | ۱۰ | `deploy/k8s` |
| ۲:۵۰ تا ۳:۰۰ | S8 مستندات و تحویل | ۳ | `docs/readme` |
| | **جمع ساخت** | **۸۰** | |

---

## مرحله‌ی ۰ — شروع و «تصمیم‌های من» (روش Q)

⏱️ ۰:۰۰ تا ۰:۱۰ · 💯 ۵ امتیاز · 🌿 `main`

🎯 قبل از نوشتن حتی یک خط کد، **مثل یک مهندس فکر کن.** روش Q چهار قدم دارد:

> **تحلیل ← سؤال ← توافق ← ساخت**

1. **تحلیل:** README را کامل بخوان و دقیق ببین چه چیزی خواسته شده.
2. **سؤال:** از خودت بپرس کجاها مطمئن نیستی. (اینجا مشتری خودت هستی.)
3. **توافق:** جواب‌ها را در بخش «تصمیم‌های من» پایین همین مرحله بنویس. این قرارداد تو با خودت است.
4. **ساخت:** حالا کدنویسی را شروع کن.

✅ **کارها:**

- [ ] پوشه‌ی پروژه را بساز، بعد `git init` و `go mod init snaplink`
- [ ] یک `.gitignore` بساز (باینری‌ها، `.env`، `*.out`، `coverage*`). برای باینری بنویس `/snaplink` (با `/` در ابتدا) یا `bin/`؛ اگر فقط `snaplink` بنویسی، Git پوشه‌ی `cmd/snaplink/` را هم نادیده می‌گیرد و `main.go` کامیت نمی‌شود.
- [ ] ریپازیتوری را در GitHub بساز و `git remote add origin …`
- [ ] همین فایل PLAN.md را در ریشه‌ی پروژه بگذار و بخش «تصمیم‌های من» را پر کن
- [ ] کامیت `docs: my decisions` و `git push`، **قبل از ۰:۱۵**
- [ ] آدرس ریپازیتوری را تا ۰:۱۵ به روشی که مدرس اعلام می‌کند تحویل بده. اگر ریپازیتوری خصوصی است، حساب GitHub مدرس (نامش روی تخته است) را از Settings → Collaborators دعوت کن.

💯 **امتیازها:**

- [ ] **(۲)** بخش «تصمیم‌های من» کامل و مشخص (نه کلی‌گویی) پر شده و تا ۱۵ دقیقه بعد از شروع آزمون روی GitHub **push** شده است. همان نسخه‌ی push‌شده نمره می‌گیرد؛ اگر بعداً تصمیمی را عوض کردی، زیر یک عنوان جدید «تغییرات بعد از شروع» بنویس.
- [ ] **(۱)** `go.mod` و `.gitignore` درست هستند و ریپازیتوری روی GitHub push شده است
- [ ] **(۲)** جریان شاخه‌ای: تا پایان آزمون دست‌کم **۴ شاخه‌ی مرحله‌ای** با **کامیت merge** در `main` ادغام شده باشد (هر کدام نیم امتیاز). پس همیشه `git merge --no-ff` بزن: merge معمولی اینجا fast-forward می‌شود و هیچ کامیت mergeی نمی‌سازد. در GitHub هم فقط دکمه‌ی **Create a merge commit** (نه Squash و نه Rebase). در `git log --graph` باید شاخه‌ها جدا دیده شوند.

💡 **جریان کار برای هر مرحله:** شاخه‌ی جدید بساز، چند کامیت کوچک بزن، بعد با `--no-ff` در `main` ادغام و push کن:

</div>

```bash
git switch -c feat/api
git add -A && git commit -m "feat: ..."
git switch main
git merge --no-ff feat/api -m "merge: feat/api"
git push origin main
```

<div dir="rtl">

### ✍️ تصمیم‌های من (My decisions)

> هر جواب ۲ تا ۵ خط باشد. **مشخص بنویس.** جمله‌ای مثل «از بهترین روش استفاده می‌کنم» جواب حساب نمی‌شود.
>
> خط «✍️ اینجا بنویس…» را **پاک کن** و جوابت را جایش بنویس (نه به‌صورت نقل‌قول با `>`). عنوان‌ها را عوض نکن، به‌خصوص «تصمیم‌های من (My decisions)» و کلمه‌های انگلیسی WHAT، STRUCTURE، DATA، CONCURRENCY، SECURITY، OUT OF SCOPE، RISKS و AI PLAN؛ تصحیح‌گر جواب‌ها را با همین عنوان‌ها پیدا می‌کند.

#### ۱. WHAT — چه چیزی می‌سازم و برای چه کسی؟ (دو جمله)

_✍️ اینجا بنویس…_

#### ۲. STRUCTURE — درخت پوشه‌ها و پکیج‌هایم، و این‌که هر پکیج چه مسئولیتی دارد

_✍️ اینجا بنویس…_

#### ۳. DATA — کلیدهای Redis من (نام کلید، نوع داده و محتوا)

_✍️ اینجا بنویس…_

#### ۴. CONCURRENCY — چطور کلیک‌ها را بدون گم شدن حتی یکی می‌شمارم، و چطور مطمئن می‌شوم دو درخواست هم‌زمان یک کد دلخواه را نگیرند؟ (هم در store درون‌حافظه‌ای و هم در Redis)

_✍️ اینجا بنویس…_

#### ۵. SECURITY — سه اقدام امنیتی مشخص (مثلاً درباره‌ی URLهای خطرناک، رمزها، کانتینر یا ورودی کاربر)

_✍️ اینجا بنویس…_

#### ۶. OUT OF SCOPE — امروز چه چیزهایی را عمداً نمی‌سازم؟

_✍️ اینجا بنویس…_

#### ۷. RISKS — کدام بخش احتمالاً زمان‌بندی‌ام را خراب می‌کند و نقشه‌ی جایگزینم چیست؟

_✍️ اینجا بنویس…_

#### ۸. AI PLAN — از هوش مصنوعی برای چه کارهایی استفاده می‌کنم و خروجی‌اش را چطور بررسی می‌کنم؟

_✍️ اینجا بنویس…_

🚩 **نقطه‌ی بازرسی ۰:** کامیت `docs: my decisions` روی `main` و push.

---

## مرحله‌ی ۱ — برنامه‌ی Go

⏱️ ۰:۱۰ تا ۱:۰۵ · 💯 ۲۵ امتیاز · 🌿 `feat/api`

🎯 API کامل طبق قرارداد README؛ اول با store درون‌حافظه‌ای و بعد با Redis.

✅ **ترتیب پیشنهادی** (بعد از هر قدم اجرا و امتحان کن):

1. **دامنه (حدود ۱۰ دقیقه)** — در `internal/link`: type `Link` با تگ‌های JSON دقیق، خطاهای ثابت (sentinel)، تابع اعتبارسنجی URL، تابع اعتبارسنجی کد دلخواه (همراه با کلمه‌های رزروشده)، و تولید کد ۶ کاراکتری با `crypto/rand`.
2. **store درون‌حافظه‌ای (حدود ۱۰ دقیقه)** — در `internal/store/memory.go`: یک map به‌همراه یک `sync.Mutex`. تابع `Hit` باید بررسی وجود لینک و افزایش کلیک را **زیر یک قفل** انجام دهد.
3. **لایه‌ی HTTP (حدود ۱۵ دقیقه)** — در `internal/api`: مسیرها با الگوهای Go 1.22، تابع‌های کمکی `writeJSON` و `writeError`، و **یک تابع واحد** که خطا را با `errors.Is` به status code تبدیل کند. ریدایرکت با `http.Redirect(w, r, url, http.StatusFound)`.
4. **main (حدود ۵ دقیقه)** — خواندن env، انتخاب store، ساخت `http.Server`، middleware لاگ و recovery، و خاموشی مرتب. حالا با `STORE=memory go run ./cmd/snaplink` نمونه‌ی curl در README را امتحان کن.
5. **Redis (حدود ۱۵ دقیقه)** — در `internal/store/redis.go`: ساخت لینک با گرفتن اتمیک کد، `HINCRBY` برای کلیک‌ها، ZSET برای لیست، و حذف کامل.

💡 **یک Redis سریع برای توسعه:**

</div>

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine --requirepass devpass

export STORE=redis
export REDIS_ADDR=localhost:6379
export REDIS_PASSWORD=devpass
go run ./cmd/snaplink
```

<div dir="rtl">

🏁 **تمام است وقتی:** همه‌ی ۷ endpoint هم با `STORE=memory` و هم با `STORE=redis` درست جواب می‌دهند، و با Ctrl+C برنامه پیام خاموشی مرتب را چاپ می‌کند.

💯 **امتیازها:**

- [ ] **(۸)** قرارداد API — با تصحیح‌گر خودکار: همه‌ی endpointها، status codeها، نام فیلدها و ترتیب خطاها
- [ ] **(۳)** طوفان هم‌زمانی — با تصحیح‌گر خودکار: ۱۰۰ کلیک هم‌زمان روی **Redis** دقیقاً ۱۰۰ شمرده شود، و از ۲۰ درخواست هم‌زمان با یک کد دلخواه یکسان فقط یکی `201` بگیرد و بقیه `409`؛ هیچ پاسخ `500`ی نیاید
- [ ] **(۳)** دامنه و اعتبارسنجی: قوانین URL، قوانین کد دلخواه به‌همراه کلمه‌های رزروشده، تولید کد با `crypto/rand`، خطاهای ثابت همراه با `errors.Is`، و یک تابع واحد برای نگاشت خطا به status
- [ ] **(۴)** اینترفیس `Store` با دو پیاده‌سازی (memory با Mutex، و redis) که با متغیر `STORE` انتخاب می‌شوند
- [ ] **(۳)** درستی Redis: کلیک‌ها با دستور اتمیک (`HINCRBY` یا `INCR`، **هرگز** GET و بعد SET)، گرفتن اتمیک کد (`HSETNX`، `SET … NX` یا اسکریپت Lua)، لیست جدیدترین‌اول با ZSET (یا معادل آن)، و حذف هم hash و هم عضو ZSET
- [ ] **(۱)** پیکربندی از env با مقدارهای پیش‌فرض؛ پیکربندی نامعتبر = خروج فوری با پیام واضح
- [ ] **(۱)** `/healthz` به Redis دست نمی‌زند؛ `/readyz` به Redis ping می‌زند (حداکثر ۲ ثانیه) و اگر قطع بود `503` برمی‌گرداند
- [ ] **(۱)** middleware: لاگ JSON برای هر درخواست با `log/slog`، و recovery از panic که `500` و `{"error":"internal error"}` برگرداند
- [ ] **(۱)** خاموشی مرتب با `SIGINT`/`SIGTERM`: فراخوانی `http.Server.Shutdown` با timeout، بستن اتصال Redis و نوشتن پیام در لاگ

💡 **نکته‌ها:**

- **گرفتن اتمیک کد:** `HSETNX link:{code} url <url>` اگر فیلد `url` در این hash از قبل وجود داشته باشد (یعنی کد قبلاً گرفته شده)، `false` برمی‌گرداند، یعنی `409`. الگوی «اول `EXISTS` بزن، بعد بنویس» زیر بار هم‌زمان شکست می‌خورد.
- **تله‌ی ظریف (امتیاز دارد):** `HINCRBY` روی کلیدی که وجود ندارد، آن را **می‌سازد**! اگر `Hit` اول `HINCRBY` بزند و بعد url را بخواند، حتی **یک کلیک معمولی** روی لینکی که قبلاً حذف شده یک hash نیمه‌کاره با `clicks: 1` زنده می‌کند؛ بعد از آن `GET /api/links/{code}` به‌جای `404` جواب دیگری می‌دهد و تصحیح‌گر دقیقاً همین را امتحان می‌کند. اول وجود لینک را بررسی کن؛ راه حل تمیز یک اسکریپت کوچک Lua است که «اگر وجود داشت، افزایش بده و url را برگردان» را اتمیک انجام دهد (`redis.NewScript` در go-redis).
- **لیست جدیدترین اول:** `ZADD links <millis> <code>` هنگام ساخت، و `ZREVRANGE links 0 -1` هنگام لیست کردن. `created_at` را با **همان دقت** امتیاز ZSET (میلی‌ثانیه) ذخیره کن؛ وگرنه دو لینکی که در یک میلی‌ثانیه ساخته شده‌اند ممکن است با ترتیب اشتباه برگردند.
- یک slice خالی (`nil`) در JSON به `null` تبدیل می‌شود! برای لیست خالی از `[]link.Link{}` یا `make` استفاده کن تا خروجی `[]` باشد.
- تولید کد با `crypto/rand`: برای هر کاراکتر `rand.Int(rand.Reader, big.NewInt(62))` و انتخاب از الفبای ۶۲ حرفی. اگر کد ساخته‌شده تکراری یا رزروشده بود، دوباره بساز.
- کد مسیر را با `r.PathValue("code")` بگیر.

🤖 **تله‌های هوش مصنوعی:**

- کلیک‌ها را با `GET` و بعد `SET` می‌شمارد؛ زیر بار هم‌زمان کلیک‌ها گم می‌شوند.
- برای تولید کد از `math/rand` استفاده می‌کند که قابل پیش‌بینی است.
- به‌جای `302` از `301` استفاده می‌کند. مرورگرها `301` را cache می‌کنند و کلیک‌های بعدی اصلاً به سرور نمی‌رسند!
- scheme را بررسی نمی‌کند و `javascript:` از دستش درمی‌رود (خطر XSS و open redirect).
- برای `POST` به‌جای `201` همان `200` را برمی‌گرداند.
- `Content-Type` را فقط برای پاسخ‌های موفق تنظیم می‌کند.

🚩 **نقطه‌ی بازرسی ۱:** چند کامیت کوچک (`feat: link domain`، `feat: memory store`، `feat: http api`، `feat: redis store`) و بعد merge در `main`.

---

## مرحله‌ی ۲ — تست‌ها

⏱️ ۱:۰۵ تا ۱:۲۰ · 💯 ۸ امتیاز · 🌿 `test/unit`

🎯 ثابت کن کدت درست کار می‌کند، **بدون نیاز به Redis**.

✅ **کارها:**

- [ ] تست جدول‌محور (table-driven) برای اعتبارسنجی URL و کد دلخواه
- [ ] تست هم‌زمانی: ۱۰۰ goroutine که هم‌زمان `Hit` را روی یک کد صدا می‌زنند، به‌همراه `sync.WaitGroup`
- [ ] تست handlerها با `net/http/httptest`
- [ ] اجرای `go test -race ./...`

🏁 **تمام است وقتی:** `go test -race -count=1 ./...` بدون هیچ Redisی سبز است.

💯 **امتیازها:**

- [ ] **(۳)** تست جدول‌محور با `t.Run` و دست‌کم ۵ حالت، شامل حالت‌های خطا که با `errors.Is` بررسی می‌شوند
- [ ] **(۲)** تست هم‌زمانی روی store درون‌حافظه‌ای: دست‌کم ۱۰۰ goroutine و `sync.WaitGroup`، بررسی دقیق تعداد نهایی کلیک‌ها، و پاس شدن با `-race`
- [ ] **(۲)** تست `httptest` برای دست‌کم ۳ endpoint، که دست‌کم یکی از آن‌ها حالت خطا باشد
- [ ] **(۱)** `go test -race ./...` بدون اجرای Redis پاس می‌شود

💡 **اسکلت یک تست جدول‌محور:**

</div>

```go
tests := []struct {
    name    string
    url     string
    wantErr error
}{
    {"https ok", "https://go.dev/doc", nil},
    {"http ok", "http://example.com", nil},
    {"empty", "", link.ErrInvalidURL},
    {"no host", "http://", link.ErrInvalidURL},
    {"ftp", "ftp://example.com", link.ErrInvalidURL},
    {"javascript", "javascript:alert(1)", link.ErrInvalidURL},
}
for _, tt := range tests {
    t.Run(tt.name, func(t *testing.T) {
        err := link.ValidateURL(tt.url)
        if !errors.Is(err, tt.wantErr) {
            t.Fatalf("got %v, want %v", err, tt.wantErr)
        }
    })
}
```

<div dir="rtl">

- تست یکپارچه با Redis اختیاری است. اگر نوشتی، وقتی متغیر محیطی مخصوصش تنظیم نشده بود آن را skip کن، مثلاً: `if os.Getenv("SNAPLINK_TEST_REDIS_ADDR") == "" { t.Skip("no redis") }`
- برای تست ریدایرکت با `httptest`، کد `302` و هدر `Location` را در `rec.Code` و `rec.Header().Get("Location")` بررسی کن.

🤖 **تله‌های هوش مصنوعی:** تست‌هایی می‌نویسد که به Redis واقعی وصل می‌شوند و در CI شکست می‌خورند؛ از `t.Parallel()` با state مشترک استفاده می‌کند؛ تست هم‌زمانی می‌نویسد ولی تعداد دقیق کلیک‌ها را بررسی نمی‌کند.

🚩 **نقطه‌ی بازرسی ۲:** کامیت `test: table-driven, concurrency and http tests` و merge.

---

## مرحله‌ی ۳ — لینوکس و اسکریپت‌های Bash

⏱️ ۱:۲۰ تا ۱:۳۵ · 💯 ۷ امتیاز · 🌿 `chore/scripts`

🎯 دو اسکریپت واقعی که هر مهندس DevOps هر روز می‌نویسد.

✅ **کارها:**

- [ ] `scripts/check-env.sh`: بررسی می‌کند همه‌ی ابزارها نصب و آماده باشند
- [ ] `scripts/smoke.sh [BASE_URL]`: یک تست دود سریع روی برنامه‌ی در حال اجرا (پیش‌فرض `http://localhost:8080`)
- [ ] `chmod +x scripts/*.sh`

🏁 **تمام است وقتی** خروجی تقریباً این شکلی باشد:

</div>

```text
$ scripts/check-env.sh
✓ go go1.26.2
✓ git 2.47.0
✓ docker 27.3.1
✓ docker daemon reachable
✓ kubectl v1.31.0
✓ kind 0.24.0
ALL GOOD

$ scripts/smoke.sh http://localhost:8080
PASS healthz
PASS readyz
PASS create link
PASS redirect (302 + Location)
PASS clicks counted
PASS invalid url (400)
PASS unknown code (404)
7 passed, 0 failed
```

<div dir="rtl">

💯 **امتیازها — هر دو اسکریپت:**

- [ ] **(۱)** در **هر دو اسکریپت** (`check-env.sh` و `smoke.sh`، هر کدام نیم امتیاز): خط اول دقیقاً `#!/usr/bin/env bash`، قبل از اولین دستور `set -euo pipefail`، بدون خطای `bash -n`، و بیت اجرایی (mode `100755`) کامیت شده باشد

💯 **امتیازها — `check-env.sh`:**

- [ ] **(۱)** وجود go، git، docker، kubectl و (kind یا minikube) را بررسی کند و برای هر کدام `✓` یا `✗` چاپ کند؛ اگر همه بودند کد خروج ۰ و در غیر این صورت ۱؛ خط آخر `ALL GOOD` یا `MISSING: …`
- [ ] **(۱)** روشن بودن Docker daemon را هم بررسی کند (`docker info`) و پیام واضح بدهد

💯 **امتیازها — `smoke.sh`:**

- [ ] **(۱)** دست‌کم ۶ بررسی با curl روی status code؛ پیشنهاد: healthz، readyz، ساخت لینک، ریدایرکت `302` با `Location` درست، شمارش کلیک، URL نامعتبر (باید `400` بدهد)، کد ناموجود (باید `404` بدهد)
- [ ] **(۱)** برای هر بررسی یک خط چاپ کند که **با** `PASS <name>` یا `FAIL <name> (expected X, got Y)` **شروع شود** (بدون رنگ یا علامت قبل از آن)، خط آخر دقیقاً به شکل `N passed, M failed` باشد (مثلاً `8 passed, 0 failed`)، و اگر چیزی شکست خورد کد خروج غیرصفر بدهد. **حتی وقتی سرور اصلاً در دسترس نیست** باید خط‌های `FAIL` و جمع‌بندی چاپ شوند، نه این‌که اسکریپت بی‌صدا متوقف شود (تصحیح‌گر این را با یک پورت بسته امتحان می‌کند)
- [ ] **(۱)** کد لینک را از پاسخ استخراج کند (هیچ کد ثابتی در اسکریپت نباشد، به‌جز یک کد عمداً ناموجود مثل `no-such-code` برای بررسی `404`)
- [ ] **(۱)** روی Compose **و** روی port-forward کلاستر Kubernetes سبز باشد

💡 **نکته‌ها:**

</div>

```bash
code=$(curl -s -o /tmp/body.json -w '%{http_code}' --max-time 5 \
  -X POST "$BASE/api/links" -d '{"url":"https://go.dev"}') || code=000

# با jq:
short=$(jq -r '.code // empty' /tmp/body.json 2>/dev/null || true)

# بدون jq:
short=$(grep -o '"code":"[^"]*"' /tmp/body.json 2>/dev/null | cut -d'"' -f4 || true)

# curl به‌طور پیش‌فرض ریدایرکت را دنبال نمی‌کند؛ پس 302 را می‌بینی
loc=$(curl -s -o /dev/null -w '%{redirect_url}' --max-time 5 "$BASE/$short" || true)
```

<div dir="rtl">

- ⚠️ با `set -e`، اگر curl وصل نشود (کد خروج ۷) یا jq و grep چیزی پیدا نکنند، اسکریپت همان‌جا و **بدون هیچ خط FAIL** می‌میرد؛ برای همین `|| code=000` و `|| true` را بگذار.
- ⚠️ تله‌ی معروف Bash: با `set -e`، دستور `((passed++))` وقتی `passed` صفر است کد خروج ۱ برمی‌گرداند و **اسکریپت را می‌کشد!** به‌جایش بنویس `passed=$((passed + 1))`.
- کاربران ویندوز: بیت اجرایی را با `git update-index --chmod=+x scripts/*.sh` ثبت کنید.
- با `command -v kind >/dev/null 2>&1` وجود یک ابزار را بدون خطا بررسی کن.

🚩 **نقطه‌ی بازرسی ۳:** کامیت `chore: env check and smoke test scripts` و merge.

---

## مرحله‌ی ۴ — Docker

⏱️ ۱:۳۵ تا ۱:۵۵ · 💯 ۹ امتیاز · 🌿 `build/docker`

🎯 یک ایمیج **کوچک، امن و سریع** برای برنامه‌ات.

✅ **کارها:**

- [ ] یک `Dockerfile` چندمرحله‌ای (multi-stage)
- [ ] یک `.dockerignore`
- [ ] build و اجرای آزمایشی

🏁 **تمام است وقتی:**

</div>

```bash
docker build -t snaplink:v1 .
docker images snaplink:v1
docker run --rm -p 8080:8080 -e STORE=memory snaplink:v1
```

<div dir="rtl">

اندازه‌ی ایمیج باید حداکثر ۳۰ مگابایت باشد. وقتی کانتینر بالا آمد، در یک ترمینال دیگر `curl -i localhost:8080/healthz` باید جواب `200` بدهد.

💯 **امتیازها:**

- [ ] **(۲)** build چندمرحله‌ای: مرحله‌ی ساخت با `golang` و مرحله‌ی نهایی `scratch`، distroless یا `alpine`
- [ ] **(۲)** اندازه‌ی ایمیج نهایی حداکثر ۳۰ مگابایت
- [ ] **(۱)** اجرا با کاربر غیر root (مثلاً `USER 65532:65532`)
- [ ] **(۱)** فایل `.dockerignore` (حذف `.git`، باینری‌ها، `.env`، `k8s/` و …)
- [ ] **(۱)** ترتیب مناسب برای cache: اول `COPY go.mod go.sum`، بعد `go mod download`، و بعد `COPY . .`
- [ ] **(۱)** باینری استاتیک با `CGO_ENABLED=0` و `-ldflags "-s -w"`؛ `ENTRYPOINT` به شکل exec (آرایه‌ای)؛ `EXPOSE 8080`
- [ ] **(۱)** `docker build` بدون خطا کار کند و کانتینر با `STORE=memory` روی `/healthz` جواب `200` بدهد

💡 **اسکلت (بقیه‌اش با خودت):**

</div>

```dockerfile
# ---------- مرحله‌ی ساخت ----------
# تگ golang باید دست‌کم برابر خط go در go.mod باشد
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/snaplink ./cmd/snaplink

# ---------- مرحله‌ی نهایی ----------
FROM scratch
# …کپی باینری، USER، EXPOSE، ENTRYPOINT
```

<div dir="rtl">

- در Dockerfile کامنت فقط در خطی جدا که با `#` شروع می‌شود مجاز است؛ `#` در انتهای یک دستور، جزو آرگومان‌های همان دستور حساب می‌شود و build را خراب می‌کند.
- تگ ایمیج `golang` باید **دست‌کم برابر** خط `go` در `go.mod` باشد. ایمیج‌های رسمی `GOTOOLCHAIN=local` دارند، پس ایمیج قدیمی‌تر build را با خطا متوقف می‌کند.
- ایمیج `scratch` هیچ shell و curlی ندارد؛ پس `docker exec … sh` کار نمی‌کند و `HEALTHCHECK` به یک فلگ در خود باینری نیاز دارد (مثلاً `-healthcheck`، مثل user-service در پروژه‌ی نهایی بوت‌کمپ). این کار اختیاری است.

🤖 **تله‌های هوش مصنوعی:** ایمیج نهایی را همان `golang` می‌گذارد (بیش از ۸۰۰ مگابایت)؛ کانتینر را با root اجرا می‌کند؛ `COPY . .` را قبل از `go mod download` می‌گذارد و cache را خراب می‌کند؛ از تگ `latest` استفاده می‌کند.

🚩 **نقطه‌ی بازرسی ۴:** کامیت `build: multi-stage dockerfile` و merge.

---

## مرحله‌ی ۵ — Docker Compose

⏱️ ۱:۵۵ تا ۲:۱۰ · 💯 ۷ امتیاز · 🌿 `build/compose`

🎯 کل سیستم (برنامه + Redis) با یک دستور بالا بیاید.

✅ **کارها:**

- [ ] فایل `compose.yaml` با دو سرویس `app` و `redis`
- [ ] فایل `.env.example` کامیت شود؛ فایل `.env` در `.gitignore` باشد
- [ ] اجرای smoke test روی Compose

🏁 **تمام است وقتی:**

</div>

```bash
cp .env.example .env
docker compose up -d --build
scripts/smoke.sh http://localhost:8080
docker compose down && docker compose up -d
curl -s localhost:8080/api/links
```

<div dir="rtl">

smoke test باید سبز باشد، و بعد از `down` و `up` (بدون `-v`) لینک‌ها هنوز باید باشند.

💯 **امتیازها:**

- [ ] **(۱)** دو سرویس `app` (ساخته‌شده از Dockerfile خودت) و `redis` (`redis:7-alpine`)
- [ ] **(۲)** healthcheck برای Redis (`redis-cli ping`) و `depends_on` با `condition: service_healthy` برای برنامه
- [ ] **(۱)** یک named volume برای داده‌ی Redis؛ داده بعد از `docker compose down` و `up` (بدون `-v`) باقی بماند
- [ ] **(۱)** پیکربندی از طریق `.env`: فایل `.env.example` کامیت شده باشد، `.env` در `.gitignore` باشد و هرگز کامیت نشود، و هیچ رمزی داخل کد Go نوشته نشده باشد
- [ ] **(۱)** برای `app`، `restart: unless-stopped`؛ پورت Redis به host منتشر (publish) **نشود**
- [ ] **(۱)** smoke test روی `docker compose up -d --build` از یک clone تمیز (بعد از `cp .env.example .env`) سبز باشد

💡 **نکته‌ها:**

- داخل Compose، آدرس Redis **نام سرویس** است، نه `localhost`: `REDIS_ADDR=redis:6379`
- برای اجرای Redis با رمز: `command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}", "--appendonly", "yes"]`. گزینه‌ی `--appendonly yes` به‌همراه volume روی `/data` باعث می‌شود داده بعد از restart باقی بماند.
- healthcheck: `["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]`
- دستور `docker compose down -v` volumeها را پاک می‌کند و داده از بین می‌رود.
- لاگ زنده: `docker compose logs -f app`

🤖 **تله‌های هوش مصنوعی:** `depends_on` را بدون شرط می‌نویسد (برنامه قبل از آماده شدن Redis بالا می‌آید)؛ پورت `6379` را منتشر می‌کند؛ Redis را بدون رمز و بدون persistence اجرا می‌کند؛ رمز را مستقیم در `compose.yaml` می‌نویسد.

🚩 **نقطه‌ی بازرسی ۵:** کامیت `build: docker compose with redis` و merge.

---

## مرحله‌ی ۶ — CI با GitHub Actions

⏱️ ۲:۱۰ تا ۲:۲۵ · 💯 ۶ امتیاز · 🌿 `ci/github-actions`

🎯 هر push و هر Pull Request به‌طور خودکار بررسی شود.

✅ **کارها:**

- [ ] فایل `.github/workflows/ci.yml` با دو job به نام‌های `test` و `build`
- [ ] این شاخه را push کن و در GitHub یک **Pull Request** باز کن
- [ ] صبر کن CI سبز شود، PR را در GitHub با دکمه‌ی **Create a merge commit** ادغام کن (نه «Squash and merge» و نه «Rebase and merge»؛ این دو کامیت merge نمی‌سازند)، و بعد با `git switch main && git pull` شاخه‌ی `main` محلی را به‌روز کن

💯 **امتیازها:**

- [ ] **(۱)** اجرا روی push به `main` و روی `pull_request`
- [ ] **(۲)** job `test`: `actions/checkout`، `actions/setup-go` (با `go-version-file: go.mod`)، بررسی gofmt که در صورت مشکل build را fail کند، `go vet ./...` و `go test -race ./...`
- [ ] **(۱)** job `build`: اجرای `docker build` با `needs: test`
- [ ] **(۱)** آخرین اجرا روی `main` سبز است و badge آن در README هست
- [ ] **(۱)** دست‌کم یک مرحله از طریق Pull Request در GitHub ادغام شده و چک CI روی آن دیده می‌شود

💡 **نکته‌ها:**

- بررسی gofmt: `test -z "$(gofmt -l .)"`
- badge: `![CI](https://github.com/<user>/<repo>/actions/workflows/ci.yml/badge.svg)`
- چون تست‌هایت به Redis نیاز ندارند، CI به سرویس Redis هم نیازی ندارد.

🤖 **تله‌های هوش مصنوعی:** از نسخه‌های قدیمی actionها استفاده می‌کند (مثلاً `@v2`)؛ تستی می‌نویسد که به Redis نیاز دارد و CI قرمز می‌شود؛ `needs: test` را فراموش می‌کند.

🚩 **نقطه‌ی بازرسی ۶:** merge از طریق Pull Request در GitHub.

---

## مرحله‌ی ۷ — Kubernetes

⏱️ ۲:۲۵ تا ۲:۵۰ · 💯 ۱۰ امتیاز · 🌿 `deploy/k8s`

🎯 برنامه با **دو رپلیکا** و Redis روی کلاستر محلی (kind یا minikube) اجرا شود.

✅ **فایل‌ها:**

</div>

```text
k8s/
├── 00-namespace.yaml    # namespace: snaplink
├── 10-configmap.yaml    # PORT، STORE=redis، REDIS_ADDR، BASE_URL
├── 11-secret.yaml       # REDIS_PASSWORD
├── 20-redis.yaml        # Deployment + Service
└── 30-app.yaml          # Deployment با ۲ رپلیکا + Service (پورت ۸۰ به ۸۰۸۰)
```

<div dir="rtl">

✅ **دستورها:**

</div>

```bash
docker compose down
docker build -t snaplink:v1 .
kind load docker-image snaplink:v1 --name exam
kubectl apply -f k8s/
kubectl -n snaplink get pods -w
```

<div dir="rtl">

- `docker compose down` پورت 8080 را آزاد می‌کند (بدون `-v`، پس داده‌ی Compose می‌ماند). در minikube به‌جای `kind load` بزن: `minikube image load snaplink:v1`
- بعد از **هر** build دوباره `kind load` کن و `kubectl -n snaplink rollout restart deploy/snaplink` بزن؛ چون تگ همان `v1` است، pod‌ها خودشان ایمیج جدید را نمی‌گیرند.
- `get pods -w` را وقتی همه `Running` شدند با Ctrl+C ببند. بعد port-forward را در یک ترمینال جدا باز نگه دار و smoke test را در ترمینال دیگر بزن:

</div>

```bash
kubectl -n snaplink port-forward svc/snaplink 8080:80
```

```bash
scripts/smoke.sh http://localhost:8080
```

<div dir="rtl">

🏁 **تمام است وقتی:** دو pod برنامه در وضعیت `Running` و `READY 1/1` هستند و smoke test روی port-forward سبز است.

💯 **امتیازها:**

- [ ] **(۱)** Namespace `snaplink`؛ و `kubectl apply -f k8s/` روی یک کلاستر تازه **در یک مرحله** کار کند
- [ ] **(۲)** ConfigMap برای تنظیمات غیرمحرمانه و Secret برای رمز Redis؛ برنامه آن‌ها را با `envFrom` یا `secretKeyRef` بخواند
- [ ] **(۲)** Deployment و Service (از نوع ClusterIP) برای Redis، با `--requirepass` که رمزش از همان Secret می‌آید
- [ ] **(۲)** Deployment برنامه: `replicas: 2`، هم `requests` و هم `limits` برای منابع، تگ ثابت ایمیج (نه `latest`)، و `imagePullPolicy: IfNotPresent`
- [ ] **(۲)** `livenessProbe` روی `/healthz` و `readinessProbe` روی `/readyz`
- [ ] **(۱)** Service برنامه به نام `snaplink` (از نوع ClusterIP) با `port: 80` و `targetPort: 8080`، تا `kubectl -n snaplink port-forward svc/snaplink 8080:80` کار کند و smoke test روی آن سبز باشد

💡 **نکته‌ها:**

- `kubectl apply -f k8s/` فایل‌ها را به **ترتیب حروف الفبا** اعمال می‌کند؛ برای همین اسم فایل‌ها با عدد شروع می‌شود تا namespace اول ساخته شود.
- اگر تگ ایمیج `latest` باشد، Kubernetes پیش‌فرض `imagePullPolicy: Always` می‌گذارد، سعی می‌کند ایمیج را از Docker Hub بکشد و به `ErrImagePull` می‌خورد. پس `snaplink:v1` و `IfNotPresent`.
- داخل کلاستر، آدرس Redis **نام Service** آن است: `REDIS_ADDR=redis:6379`.
- Kubernetes در `args` متغیرهای محیطی را با شکل `$(NAME)` جایگزین می‌کند. پس برای Redis می‌شود نوشت: `args: ["--requirepass", "$(REDIS_PASSWORD)"]`، به شرطی که `REDIS_PASSWORD` از Secret در `env` آمده باشد.
- چون با port-forward تست می‌کنی، `BASE_URL` را در ConfigMap برابر `http://localhost:8080` بگذار.
- یادت باشد base64 در Secret **رمزنگاری نیست**. در پروژه‌ی واقعی Secret را کامیت نمی‌کنیم؛ اینجا مجاز است، ولی یک کامنت درباره‌اش بنویس.
- **liveness را روی `/readyz` نگذار!** اگر Redis قطع شود، Kubernetes همه‌ی podهای سالم برنامه را بی‌دلیل restart می‌کند.
- اگر Redis موقع شروع برنامه هنوز آماده نیست، برنامه نباید crash کند: HTTP را بالا بیاور و بگذار `/readyz` تا وصل شدن Redis جواب `503` بدهد. (اگر برنامه‌ات قبل از HTTP منتظر Redis می‌ماند، یک `startupProbe` روی `/healthz` با `failureThreshold: 30` لازم داری.)
- timeout پیش‌فرض probeها ۱ ثانیه است، ولی `/readyz` ممکن است تا ۲ ثانیه منتظر ping بماند. برای readiness `timeoutSeconds: 3` بگذار.
- اگر pod مربوط به Redis روی `ImagePullBackOff` ماند (Docker Hub در دسترس نیست)، ایمیج را از Docker خودت داخل کلاستر بارگذاری کن: `kind load docker-image redis:7-alpine --name exam`
- **ابزارهای رفع اشکال:**

</div>

```bash
kubectl -n snaplink get pods
kubectl -n snaplink describe pod <name>
kubectl -n snaplink logs deploy/snaplink
kubectl -n snaplink get events --sort-by=.lastTimestamp
```

<div dir="rtl">

🤖 **تله‌های هوش مصنوعی:** `image: snaplink:latest`؛ بدون محدودیت منابع؛ liveness روی `/readyz`؛ رمز Redis به‌صورت متن ساده در خود Deployment.

🚩 **نقطه‌ی بازرسی ۷:** کامیت `deploy: kubernetes manifests` و merge.

---

## مرحله‌ی ۸ — مستندات، یادداشت AI و تحویل

⏱️ ۲:۵۰ تا ۳:۰۰ · 💯 ۳ امتیاز · 🌿 `docs/readme`

🎯 کسی که ریپازیتوری‌ات را باز می‌کند، در ۲ دقیقه بفهمد این چیست و چطور اجرایش کند.

💡 **اسکلت README خودت:**

</div>

```markdown
# SnapLink
![CI](https://github.com/<user>/<repo>/actions/workflows/ci.yml/badge.svg)

یک خط معرفی.

## Architecture
(نمودار ASCII یا Mermaid)

## Run
### Local (STORE=memory)
### Docker Compose
### Kubernetes (kind)

## Configuration
(جدول متغیرهای محیطی)

## AI usage
- ابزارها:
- برای چه کاری:
- اشتباه‌هایی که AI کرد و من درستشان کردم:
```

<div dir="rtl">

💯 **امتیازها:**

- [ ] **(۱)** README: معرفی، نمودار معماری (ASCII یا Mermaid)، نحوه‌ی اجرا (memory، Compose، Kubernetes) و جدول متغیرهای محیطی
- [ ] **(۱)** بخش AI usage: ابزارها، کاربردشان، و دست‌کم یک اشتباه AI که خودت درستش کردی
- [ ] **(۱)** تاریخچه‌ی Git: دست‌کم ۱۰ کامیت معنادار (به‌جز کامیت‌های merge) که در طول آزمون پخش شده باشند (فاصله‌ی اولین تا آخرین کامیت دست‌کم ۹۰ دقیقه)، پیام‌ها به سبک conventional (`feat:`، `fix:`، `test:`، `build:`، `ci:`، `docs:`، `chore:`)، و هیچ رمز واقعی یا باینری در ریپازیتوری (Secret نمایشی Kubernetes با کامنت مجاز است)

✅ **چک‌لیست ۵ دقیقه‌ی آخر:**

- [ ] همه‌ی شاخه‌ها در `main` ادغام و push شده‌اند
- [ ] CI روی `main` سبز است
- [ ] برنامه در Kubernetes در حال اجراست و port-forward روی `8080` برای تصحیح‌گر آماده است
- [ ] جدول خودارزیابی (پایین همین فایل) پر شده است

---

## ⭐ امتیازهای اضافه (توصیه: بعد از تمام شدن مراحل اصلی) · حداکثر +۱۵

| کد | چالش | امتیاز |
|---|---|---|
| B1 | **متریک‌های Prometheus** روی `/metrics`: شمارنده‌ی `http_requests_total` با برچسب‌های `method`، `path` و `status` (مقدار `path` الگوی مسیر باشد مثل `/{code}`، نه خود کد)، هیستوگرام `http_request_duration_seconds`، و شمارنده‌های `snaplink_redirects_total` و `snaplink_links_created_total` | +۴ |
| B2 | **Ingress** (با ingress-nginx): میزبان `snaplink.local` به Service برنامه برود، و درخواست واقعاً از کنترلر ingress-nginx رد شود (فقط وجود شیء Ingress کافی نیست؛ راهنمایی B2 را ببین) | +۳ |
| B3 | **چارت Helm** در `charts/snaplink/` با valueهای `image.tag`، `replicaCount` و `resources` که **کل سیستم** را می‌سازد (برنامه، Redis، ConfigMap و Secret)؛ دستور `helm install snaplink charts/snaplink -n snaplink-helm --create-namespace` کار کند | +۴ |
| B4 | **لینک‌های تاریخ‌دار:** فیلد اختیاری `ttl_seconds` (عدد صحیح ۱ تا ۳۱۵۳۶۰۰۰) هنگام ساخت. پاسخ فیلد `expires_at` (RFC 3339) دارد. بعد از انقضا، `GET /{code}` و `GET /api/links/{code}` جواب `404` می‌دهند و لینک در لیست هم نیست. مقدار نامعتبر (`0`، منفی، اعشاری، رشته) خطای `400` دارد | +۴ |

💡 **راهنمایی B1:** چرا `path` باید الگوی مسیر باشد؟ چون اگر هر کد یک مقدار جدید برچسب بسازد، تعداد سری‌های زمانی بی‌نهایت می‌شود (مشکل cardinality). از Go 1.23 به بعد، ServeMux الگوی مسیر را در `r.Pattern` می‌گذارد، ولی **فقط موقع مسیریابی**: در middleware آن را **بعد از** `next.ServeHTTP(w, r)` بخوان (قبلش خالی است). مقدارش متد را هم دارد (مثلاً `GET /{code}`) که قبول است؛ برای درخواستی که به هیچ الگویی نخورده خالی است، پس آن را `unmatched` بگذار، نه `r.URL.Path`. مسیر `/metrics` را هم با متد ثبت کن: `GET /metrics`. (در Go 1.22 از `mux.Handler(r)` استفاده کن.)

💡 **راهنمایی B3:** چارت را در یک namespace جدا (`snaplink-helm`) نصب کن تا با منابعی که در S7 با `kubectl apply -f k8s/` ساخته‌ای تداخل نداشته باشد (اگر در همان namespace نصب کنی، Helm با خطای `invalid ownership metadata` متوقف می‌شود). استقرار S7 را پاک نکن؛ تصحیح روی همان انجام می‌شود.

💡 **راهنمایی B4:** برای `ttl_seconds` از `*int64` استفاده کن تا «نبودن فیلد» از «صفر» جدا شود؛ `1.5` و `"10"` در decode خطا می‌دهند و باید `400` شوند. با `EXPIRE` یا `SET … EX` در Redis کلید خودش پاک می‌شود، **ولی عضو ZSET پاک نمی‌شود!** موقع لیست کردن، کدهایی را که hash آن‌ها دیگر وجود ندارد از ZSET حذف کن (پاک‌سازی تنبل یا lazy cleanup).

💡 **راهنمایی B2 در kind:** کلاستر `exam` را پاک نکن؛ لازم نیست از نو بسازی. این دستورها روی کلاستر معمولی kind امتحان شده‌اند (ایمیج‌های ingress-nginx از `registry.k8s.io` می‌آیند؛ اگر در ایران دانلود نشدند، این امتیاز را رها کن):

</div>

```bash
kubectl label node exam-control-plane ingress-ready=true
kubectl apply -f https://kind.sigs.k8s.io/examples/ingress/deploy-ingress-nginx.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod -l app.kubernetes.io/component=controller --timeout=180s
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8081:80
```

<div dir="rtl">

و در ترمینال دیگر: `curl -i -H 'Host: snaplink.local' http://localhost:8081/healthz` باید `200` بدهد. در Ingress خودت `ingressClassName: nginx` بگذار.

---

## 🎤 دفاع حضوری — چه انتظاری داشته باش (۲۰ امتیاز، بدون هوش مصنوعی)

| بخش | چه اتفاقی می‌افتد | امتیاز |
|---|---|---|
| D1 | مسیر کامل یک درخواست را در کد خودت نشان می‌دهی: از router به handler، از handler به store، از store به Redis، و در آخر پاسخ | ۵ |
| D2 | یک سؤال «چرا؟» درباره‌ی یکی از تصمیم‌هایت | ۵ |
| D3 | مدرس چیزی را در استقرار تو خراب می‌کند؛ حدود ۳ دقیقه وقت داری که با لاگ‌ها و `kubectl` مشکل را پیدا و درست کنی | ۵ |
| D4 | یک تغییر کوچک زنده در کمتر از ۳ دقیقه، بدون هوش مصنوعی | ۵ |

**مقیاس هر بخش:** ۵ = واضح و درست · ۳ = نسبی · ۱ = مبهم · ۰ = نمی‌داند

**قوانین دفاع:** حدود ۷ تا ۱۲ دقیقه روی لپ‌تاپ خودت. مستندات رسمی (مثل pkg.go.dev و kubernetes.io) مجاز است، ولی هیچ ابزار هوش مصنوعی (حتی Copilot و افزونه‌های ادیتور) مجاز نیست؛ قبل از دفاع آن‌ها را خاموش کن.

**برای تمرین، قبل از دفاع به این‌ها برای خودت جواب بده:**

- مسیر `GET /{code}` را از router تا Redis در کد خودت دنبال کن.
- اگر Redis قطع شود، `/healthz` و `/readyz` چه جوابی می‌دهند و Kubernetes با هر کدام چه می‌کند؟
- چرا با `STORE=memory` نمی‌شود دو رپلیکا داشت؟
- یک pod در وضعیت `CrashLoopBackOff` است. قدم‌به‌قدم چه می‌کنی؟

> ⚠️ **قانون «توضیح بده یا از دست بده»:** اگر بعد از دو سؤال ساده‌تر نتوانی یک مورد امتیازی (یک چک‌باکس همین فایل) را توضیح بدهی، امتیاز همان مورد صفر می‌شود؛ چه امتیاز ساخت باشد و چه امتیاز اضافه.

---

## 📊 جدول خودارزیابی (قبل از تحویل پر کن)

| مرحله | حداکثر | تخمین من | نمره‌ی مدرس |
|---|---|---|---|
| S0 شروع و تصمیم‌ها | ۵ | | |
| S1 برنامه‌ی Go | ۲۵ | | |
| S2 تست‌ها | ۸ | | |
| S3 لینوکس و Bash | ۷ | | |
| S4 Docker | ۹ | | |
| S5 Docker Compose | ۷ | | |
| S6 CI | ۶ | | |
| S7 Kubernetes | ۱۰ | | |
| S8 مستندات و تاریخچه | ۳ | | |
| **جمع ساخت** | **۸۰** | | |
| D دفاع حضوری | ۲۰ | — | |
| امتیاز اضافه (B1 تا B4) | ۱۵ | | |
| **نمره‌ی نهایی** | **۱۰۰ (+۱۵)** | | |

**نمره‌ی قبولی: ۶۰** (نمره‌ی نهایی به نزدیک‌ترین عدد صحیح گرد می‌شود). موفق باشی! 🐹

</div>
