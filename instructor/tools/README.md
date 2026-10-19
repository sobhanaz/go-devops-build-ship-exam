# ساخت دوباره‌ی PDFها

همه‌ی PDFها از فایل‌های `.md` ساخته می‌شوند. بعد از هر تغییر در متن‌ها:

```bash
cd instructor/tools
npm install          # فقط بار اول (به اینترنت نیاز دارد)
node build-pdfs.mjs  # همه‌ی PDFها را دوباره می‌سازد
```

- نیازمندی‌ها: Node.js نسخه‌ی ۱۸ به بعد و Google Chrome (یا Chromium یا Brave). اگر Chrome در مسیر استاندارد نیست: `CHROME_PATH=/path/to/chrome node build-pdfs.mjs`
- فونت‌ها (Vazirmatn و JetBrains Mono، با مجوز آزاد OFL) در پوشه‌ی `fonts/` هستند؛ ساخت PDF به اینترنت نیاز ندارد.
- خروجی دانشجوها در پوشه‌ی `PDF/` و راهنمای مدرس در پوشه‌ی `instructor/` ساخته می‌شود.
- متن فارسی در فایل‌های `.md` داخل `<div dir="rtl">` است تا در GitHub و VS Code درست نمایش داده شود. بلوک‌های کد بیرون از این div هستند؛ موقع ویرایش همین ساختار را نگه دارید.
