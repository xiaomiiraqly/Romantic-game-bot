#!/bin/bash

# Скрипт установки Telegram бота для игры пар на Ubuntu/Debian VDS
# Автор: MPR_XO
# Версия: 1.0

set -e  # Остановить выполнение при ошибке

echo "🚀 Начинаем установку Telegram бота для игры пар..."

# Проверяем, что скрипт запущен от root или с sudo
if [ "$EUID" -ne 0 ]; then
    echo "❌ Пожалуйста, запустите скрипт с правами root или через sudo:"
    echo "sudo bash install.sh"
    exit 1
fi

# Обновляем систему
echo "📦 Обновляем систему..."
apt update && apt upgrade -y

# Устанавливаем необходимые пакеты
echo "📦 Устанавливаем необходимые пакеты..."
apt install -y python3 python3-pip python3-venv git htop nano ufw fail2ban

# Создаем пользователя для бота
echo "👤 Создаем пользователя для бота..."
if ! id "telegram-bot" &>/dev/null; then
    useradd -m -s /bin/bash telegram-bot
    echo "✅ Пользователь telegram-bot создан"
else
    echo "ℹ️ Пользователь telegram-bot уже существует"
fi

# Создаем директорию для бота
BOT_DIR="/opt/telegram-bot"
echo "📁 Создаем директорию для бота: $BOT_DIR"
mkdir -p $BOT_DIR
chown telegram-bot:telegram-bot $BOT_DIR

# Копируем файлы бота
echo "📋 Копируем файлы бота..."
cp -r . $BOT_DIR/
chown -R telegram-bot:telegram-bot $BOT_DIR

# Переходим в директорию бота
cd $BOT_DIR

# Создаем виртуальное окружение
echo "🐍 Создаем виртуальное окружение Python..."
sudo -u telegram-bot python3 -m venv venv

# Активируем виртуальное окружение и устанавливаем зависимости
echo "📦 Устанавливаем зависимости Python..."
sudo -u telegram-bot bash -c "source venv/bin/activate && pip install --upgrade pip"
sudo -u telegram-bot bash -c "source venv/bin/activate && pip install -r requirements.txt"

# Создаем директории для логов
echo "📁 Создаем директории для логов..."
mkdir -p logs
chown telegram-bot:telegram-bot logs

# Создаем systemd сервис
echo "⚙️ Создаем systemd сервис..."
cat > /etc/systemd/system/telegram-bot.service << EOF
[Unit]
Description=Telegram Bot for Couples Game
After=network.target

[Service]
Type=simple
User=telegram-bot
Group=telegram-bot
WorkingDirectory=$BOT_DIR
Environment=PATH=$BOT_DIR/venv/bin
ExecStart=$BOT_DIR/venv/bin/python main.py
Restart=always
RestartSec=10

# Логирование
StandardOutput=journal
StandardError=journal
SyslogIdentifier=telegram-bot

[Install]
WantedBy=multi-user.target
EOF

# Перезагружаем systemd
systemctl daemon-reload

# Настраиваем firewall
echo "🔥 Настраиваем firewall..."
ufw --force enable
ufw allow ssh
ufw allow out 443
ufw allow out 80

# Настраиваем fail2ban
echo "🛡️ Настраиваем fail2ban..."
systemctl enable fail2ban
systemctl start fail2ban

# Создаем скрипт управления ботом
echo "📝 Создаем скрипт управления ботом..."
cat > /usr/local/bin/telegram-bot << EOF
#!/bin/bash

case "\$1" in
    start)
        echo "🚀 Запускаем бота..."
        systemctl start telegram-bot
        ;;
    stop)
        echo "⏹️ Останавливаем бота..."
        systemctl stop telegram-bot
        ;;
    restart)
        echo "🔄 Перезапускаем бота..."
        systemctl restart telegram-bot
        ;;
    status)
        echo "📊 Статус бота:"
        systemctl status telegram-bot
        ;;
    logs)
        echo "📋 Логи бота:"
        journalctl -u telegram-bot -f
        ;;
    update)
        echo "🔄 Обновляем бота..."
        cd $BOT_DIR
        sudo -u telegram-bot git pull
        sudo -u telegram-bot bash -c "source venv/bin/activate && pip install -r requirements.txt"
        systemctl restart telegram-bot
        ;;
    *)
        echo "Использование: telegram-bot {start|stop|restart|status|logs|update}"
        exit 1
        ;;
esac
EOF

chmod +x /usr/local/bin/telegram-bot

echo ""
echo "✅ Установка завершена!"
echo ""
echo "📋 Следующие шаги:"
echo "1. Скопируйте env.example в .env и настройте переменные:"
echo "   sudo cp $BOT_DIR/env.example $BOT_DIR/.env"
echo "   sudo nano $BOT_DIR/.env"
echo ""
echo "2. Настройте токен бота в файле .env:"
echo "   BOT_TOKEN=your_actual_bot_token_here"
echo ""
echo "3. Запустите бота:"
echo "   telegram-bot start"
echo ""
echo "4. Проверьте статус:"
echo "   telegram-bot status"
echo ""
echo "5. Для просмотра логов:"
echo "   telegram-bot logs"
echo ""
echo "📁 Файлы бота находятся в: $BOT_DIR"
echo "📋 Логи доступны через: telegram-bot logs"
echo ""
echo "🎉 Бот готов к работе!"
