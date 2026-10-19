# 🚀 Build & Ship — Go + DevOps Exam

> A 3-hour, two-version practical exam (Go app → tests → Bash → Docker → Compose → GitHub Actions → Kubernetes) for students of
> [go-from-beginner-to-pro](https://github.com/sobhanaz/go-from-beginner-to-pro) and
> [linux-go-devops-bootcamp](https://github.com/Tecso-Dev/linux-go-devops-bootcamp). All student material is in Persian.

<div dir="rtl">

## چالش «بساز و منتشر کن»

یک آزمون عملی ۳ ساعته که دانشجو در آن یک میکروسرویس Go را **از پوشه‌ی خالی می‌سازد** و مثل یک مهندس DevOps **منتشرش می‌کند**: تست، اسکریپت Bash، Docker، Docker Compose، CI با GitHub Actions و Kubernetes.

| | نسخه‌ی A — MiniBank | نسخه‌ی B — SnapLink |
|---|---|---|
| اپلیکیشن | دفتر کل بانکی (حساب، واریز، برداشت، انتقال اتمیک) | کوتاه‌کننده‌ی لینک (ریدایرکت، شمارش کلیک، کد دلخواه) |
| datastore | PostgreSQL | Redis |
| تله‌ی هم‌روندی | گم شدن پول در انتقال‌های هم‌زمان | گم شدن کلیک‌ها و گرفتن هم‌زمان یک کد |

**قوانین:** ۳ ساعت، انفرادی، همه‌ی ابزارها آزاد (حتی هوش مصنوعی) · ۸۰ امتیاز ساخت + ۲۰ دفاع حضوری بدون AI + ۱۵ امتیاز اضافه · قبولی ۶۰ · قانون «توضیح بده یا از دست بده».

## 📁 ساختار

| مسیر | محتوا |
|---|---|
| [`START-HERE.md`](START-HERE.md) | چه فایلی را به چه کسی و چه زمانی بدهید |
| [`PDF/`](PDF/) | PDFهای دانشجو (README و PLAN هر نسخه + چک‌لیست آماده‌سازی) |
| [`00-setup-checklist/`](00-setup-checklist/) | چک‌لیست آماده‌سازی (یک هفته قبل از آزمون) |
| [`version-A-minibank/`](version-A-minibank/) | README و PLAN نسخه‌ی A |
| [`version-B-snaplink/`](version-B-snaplink/) | README و PLAN نسخه‌ی B |
| [`instructor/`](instructor/) | راهنمای مدرس، تصحیح‌گرهای خودکار، راه‌حل‌های مرجع و ابزار ساخت PDF |

## ✅ راه‌حل‌های مرجع

پوشه‌ی [`instructor/reference/`](instructor/reference/) برای هر دو نسخه یک راه‌حل کامل دارد (همه‌ی ۹ مرحله و همه‌ی امتیازهای اضافه)، با تاریخچه‌ی Git مرحله‌به‌مرحله. هر دو روی Docker Compose، Kubernetes (kind با ۲ رپلیکا)، Helm و Ingress تست شده‌اند و از تصحیح‌گر نمره‌ی کامل خودکار گرفته‌اند.

## 🧪 تصحیح خودکار

```bash
python3 instructor/graders/grade_minibank.py --url http://localhost:8080 --repo /path/to/student-repo --namespace minibank
python3 instructor/graders/grade_snaplink.py --url http://localhost:8080 --repo /path/to/student-repo --namespace snaplink
```

جزئیات کامل در [`instructor/INSTRUCTOR-GUIDE.md`](instructor/INSTRUCTOR-GUIDE.md).

</div>
