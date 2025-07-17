// Инициализация Telegram Web App
const tg = window.Telegram.WebApp;

// Основная функция для взаимодействия с Telegram
function init() {
    // Показываем кнопку "Закрыть" в интерфейсе Mini App
    tg.MainButton.show();
    tg.MainButton.setText("Закрыть");
    tg.MainButton.onClick(() => {
        tg.close(); // Закрыть Mini App при нажатии на кнопку
    });

    // Обработка нажатия на кнопку внутри приложения
    const button = document.getElementById("mainButton");
    const responseText = document.getElementById("responseText");

    button.addEventListener("click", () => {
        responseText.textContent = "Кнопка нажата!";
        tg.sendData("Данные отправлены в Telegram"); // Отправка данных в Telegram
    });
}

// Инициализация приложения
tg.ready();
init();