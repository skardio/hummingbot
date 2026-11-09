source ~/.venvs/bot/bin/activate
cd /home/mo/repos/hummingbot
nohup python -m multi_coin_grid_pro.services.momentum_signal_service \
  --config multi_coin_grid_pro/config/momentum_signal_service.yaml \
  --log-level INFO \
  > logs/momentum_live.log 2>&1 &
echo "PID: $!"

cd /home/mo/repos/hummingbot
source .venv/bin/activate
python track_v5_paper.py

  > //home/mo/repos/hummingbot/logs/momentum_live.log 2>&1 &  python3 -m pytest multi_coin_grid_pro/tests/unit/ -q



source ~/.venvs/bot/bin/activate
cd /home/mo/repos/hummingbot



python -m euro refresh
python -m euro bot
python -m euro generate --count 10


source ~/.venvs/bot/bin/activate
cd /home/mo/repos/hummingbot
bin/hummingbot.py


instaleer package:
sudo apt install ./code_1.139.1-1790309529_amd64.deb

ls je VS Code via Ubuntu, Debian of Linux Mint met APT hebt geïnstalleerd, kun je meestal gewoon updaten met:
sudo apt update
sudo apt install --only-upgrade code

Dit is een Euro-analyse- en Telegrambot. Het programma:

- haalt historische trekkingen op;
- bewaart ze in `data/euro.sqlite`;
- analyseert vaak en weinig getrokken nummers;
- genereert combinaties op basis van historische frequenties;
- kan combinaties naar Telegram sturen;
- kan continu luisteren naar het Telegramcommando `/generate`;
- kan wekelijks automatisch draaien.

Het voorspelt geen winnende nummers; Euro blijft willekeurig.

### Starten op Linux/macOS

Open een terminal in `/home/mo/repos/hummingbot` en voer uit:

```bash
cd euro_telegram
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Bekijk daarna alle commando’s:

```bash
python -m euro --help
```

Omdat er al een database aanwezig is, kun je direct proberen:

```bash
python -m euro analyze
```

Of tien combinaties genereren:

```bash
python -m euro generate --count 10
```

Historische resultaten bijwerken:

```bash
python -m euro refresh
```

### Telegram instellen

Maak eerst het configuratiebestand:

```bash
cp .env.example .env
```

Vul in `.env` je gegevens in:

```env
TELEGRAM_BOT_TOKEN=jouw_bot_token
TELEGRAM_CHAT_ID=jouw_chat_id
RUN_DAY=friday
RUN_TIME=10:00
```

Controleer de verbinding:

```bash
python -m euro telegram-check
```

Stuur een testbericht:

```bash
python -m euro telegram-test
```

Eenmalig verversen, genereren en versturen:

```bash
python -m euro once --count 10
```

De bot continu laten luisteren naar `/generate`:

```bash
python -m euro bot
```

Wekelijks automatisch laten versturen volgens `RUN_DAY` en `RUN_TIME`:

```bash
python -m euro schedule
```

Start niet met `python euro/main.py`: dat kan misgaan door de relatieve imports. Gebruik vanuit de map `euro_telegram` altijd `python -m euro ...`. Stop een continu draaiende bot of scheduler met `Ctrl+C`.
