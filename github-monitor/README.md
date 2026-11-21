# Free marketplace monitor on GitHub Actions (Wallapop + Vinted → Telegram)

Runs every 5 minutes on GitHub's computers. No server, no PC, no cost.

## Why a PUBLIC repository?
GitHub Free gives private repos only 2,000 Actions minutes a month, and a check every 5 minutes uses far more than that. In a **public** repo the minutes are free and unlimited, so this never touches the allowance your other (private) hourly action uses.
Public does **not** expose your secrets: your Telegram token and your searches are stored as encrypted **Secrets**, so only the code is visible, and the code contains nothing personal.

## 1. Telegram
1. @BotFather → `/newbot` → copy the **token** (make a new bot; never reuse a token you've shared).
2. @userinfobot → copy your **Id**.
3. Open your new bot and press **Start**.

## 2. Create the repository
1. github.com → **New repository** → name it e.g. `marketplace-monitor` → **Public** → Create.
2. **Add file → Upload files**: drag in everything from this folder (including the `.github` folder). If `.github` doesn't upload, choose **Add file → Create new file**, type `.github/workflows/monitor.yml` as the name and paste the contents of that file.

## 3. Add your three secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:
| Name | Value |
|---|---|
| `TELEGRAM_TOKEN` | the token from BotFather |
| `TELEGRAM_CHANNEL` | your Id from @userinfobot |
| `SEARCHES_JSON` | your searches: copy `searches.example.json`, edit it, paste the whole thing |

To change searches later, edit the `SEARCHES_JSON` secret. Each `{ ... }` block is one search; copy a block to add one. Wallapop needs `latitude`/`longitude`; Vinted needs `vinted_domain` (`es`, `it`, `fr`...).

## 4. Start it
Repo → **Actions** tab → enable workflows if asked → **Marketplace monitor** → **Run workflow**. The first run only remembers what already exists; you get alerts for new listings from the next run on.
Then it runs by itself every ~5 minutes (GitHub can be a few minutes late at busy times).

## Good to know
- **Idle pause:** GitHub may pause scheduled runs in public repos after about 60 days without any repo activity. It emails you; click **Enable workflow** on the Actions tab (or make any small edit).
- **Blocking:** Vinted may block GitHub's server addresses. If a search finds nothing, the run log says so. Then run the Docker version (`Personal-monitor.zip`) on a home PC/Raspberry Pi instead.
- **Facebook** is not included on purpose: logging in from GitHub's servers would likely get your account flagged.
- Not affiliated with Wallapop or Vinted. Use responsibly and keep checks to a sensible rate.
