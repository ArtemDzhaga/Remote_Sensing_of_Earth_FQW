workspace "Система построения и улучшения ЦМР" {

    model {
        researcher = person "Исследователь" {
            description "Разработчик системы. Загружает данные Sentinel-1, запускает InSAR и обучение ML моделей"
        }

        sentinel1 = softwareSystem "Sentinel-1 (STAC / ASF)" {
            description "Источник SAR: RTC и SLC (Planetary Computer STAC, ASF datapool)"
        }

        openDemSources = softwareSystem "Открытые глобальные DEM" {
            description "Эталонная модель рельефа (например Copernicus COP30 через OpenTopography) для обучения и валидации"
        }

        group "Исследование горного рельефа" {
            demSystem = softwareSystem "Система построения и улучшения ЦМР" {

                storage = container "Хранилище данных" {
                    description "Локальная файловая система проекта (outputs/YYYY-MM-DD, data/raw|processed); при необходимости — адаптер под объектное хранилище S3-совместимое"
                    technology "Local FS (расширяемо до S3/Yandex Object Storage)"
                }

                dataIngestion = container "Сервис загрузки" {
                    description "Автоматизированная загрузка снимков и метаданных (STAC, OpenTopography, ASF SLC)"
                    technology "Python / pystac-client / earthaccess"
                }

                qualityReport = container "Отчёты и визуализация качества" {
                    description "2D/3D DEM, гистограммы, интерактивный HTML (PyVista), сравнение SAR vs DEM"
                    technology "Python / Rasterio / Matplotlib / PyVista"
                }

                insarPipeline = container "InSAR Pipeline" {
                    description "Генерация базовой ЦМР через фазовую информацию (SLC); каркас SNAP + SNAPHU"
                    technology "ESA SNAP GPT / SNAPHU"

                    coregistration = component "Корегистрация снимков" {
                        description "Выравнивание Master и Slave сцен с субпиксельной точностью"
                    }
                    interferogram = component "Генерация интерферограммы" {
                        description "Вычисление разности фаз и удаление плоской земли"
                    }
                    deburst = component "S-1 Deburst & Filter" {
                        description "Устранение стыков зондирования и фильтрация шумов (Goldstein)"
                    }
                    phaseUnwrapping = component "Развёртка фазы (SNAPHU)" {
                        description "Перевод циклической фазы в непрерывные значения высоты"
                    }
                    phaseToHeight = component "Phase to Height" {
                        description "Геометрическое преобразование фазы в абсолютную высоту"
                    }

                    coregistration -> interferogram "Выровненные стеки"
                    interferogram -> deburst "Сырая интерферограмма"
                    deburst -> phaseUnwrapping "Отфильтрованная фаза"
                    phaseUnwrapping -> phaseToHeight "Развёрнутая фаза"
                }

                featureEngineer = container "Модуль подготовки признаков" {
                    description "Расчёт уклонов (Slope), нормализация, нарезка патчей"
                    technology "Python / Rasterio / GDAL"
                }

                mlTraining = container "Сервис обучения ML" {
                    description "Обучение нейросети для коррекции ошибок DEM/InSAR"
                    technology "Python / PyTorch (планируется)"

                    patchGenerator = component "Patch Generator" {
                        description "Нарезка снимков на тайлы с перекрытием"
                    }
                    inputStacker = component "Feature Stacker" {
                        description "Сборка тензора входных каналов"
                    }
                    modelArch = component "Сегментационная сеть" {
                        description "Кодировщик + декодёр (например ResNet-Unet)"
                    }
                    lossCalculator = component "Slope-Aware Loss" {
                        description "Функция потерь с учётом крутизны рельефа"
                    }

                    patchGenerator -> inputStacker "Подготовка чанков данных"
                    inputStacker -> modelArch "Подача тензора в сеть"
                    modelArch -> lossCalculator "Оптимизация относительно эталонного DEM"
                }

                webApp = container "Интерфейс визуализации" {
                    description "Отображение ЦМР, профилей рельефа и метрик"
                    technology "Streamlit / Folium (планируется)"
                }
            }
        }

        researcher -> webApp "Анализирует карты и запускает инференс"
        researcher -> dataIngestion "Настраивает параметры загрузки"

        sentinel1 -> dataIngestion "SAR данные (RTC/SLC)"
        openDemSources -> dataIngestion "Эталонные высоты"

        dataIngestion -> storage "Сохраняет сырые и обработанные данные"
        storage -> insarPipeline "Входные SLC и промежуточные продукты"
        storage -> qualityReport "Растры для отчётов"

        insarPipeline -> featureEngineer "InSAR DEM и производные"
        featureEngineer -> mlTraining "Подготовленные признаки"

        mlTraining -> storage "Веса модели и предсказания DEM"
        qualityReport -> researcher "Отчёты HTML/PNG/Markdown"
        storage -> webApp "Данные для визуализации"
    }

    views {
        systemContext demSystem {
            include *
            autolayout lr
            title "Контекстная диаграмма системы (Sentinel-1 + DEM + ML)"
        }

        container demSystem {
            include *
            autolayout lr
            title "Контейнерная архитектура системы"
        }

        component insarPipeline {
            include *
            autolayout lr
            title "Компоненты InSAR конвейера"
        }

        component mlTraining {
            include *
            autolayout lr
            title "Компоненты ML ядра"
        }

        styles {
            element "Person" {
                background "#facc15"
                color "#000000"
                shape "person"
            }
            element "SoftwareSystem" {
                background "#91c9f7"
                color "#000000"
            }
            element "Container" {
                background "#ffffff"
                border "solid"
                color "#000000"
            }
            element "Component" {
                background "#e8f5e9"
                color "#000000"
            }
        }
    }
}
