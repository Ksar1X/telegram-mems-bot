"""
processor.py — Логика Face Swap и подготовки стикеров (512×512 PNG).

Поддерживает два бэкенда (переключается через config.json → "backend"):
  • "insightface"  — локальная InSwapper-модель (требует GPU / хорошего CPU)
  • "paste_simple" — упрощённый фоллбэк: вырезает лицо и вставляет в шаблон
                    без нейросетевого свапа (полезно для отладки без GPU)
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ─── Базовый детектор лиц (используется обоими бэкендами) ───────────────────

class FaceDetector:
    """Обёртка над InsightFace FaceAnalysis для детекции и выравнивания лиц."""

    def __init__(self, providers: list[str] | None = None):
        # Импорт здесь, чтобы приложение поднималось даже без insightface
        try:
            from insightface.app import FaceAnalysis
            self._app = FaceAnalysis(
                name="buffalo_l",
                providers=providers or ["CPUExecutionProvider"],
            )
            self._app.prepare(ctx_id=0, det_size=(640, 640))
            self._available = True
        except ImportError:
            logger.warning("insightface не установлен — детекция недоступна.")
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def get_faces(self, img_bgr: np.ndarray) -> list:
        """Возвращает список Face-объектов InsightFace, отсортированных по размеру bbox."""
        if not self._available:
            return []
        faces = self._app.get(img_bgr)
        return sorted(faces, key=lambda f: f.bbox[2] * f.bbox[3], reverse=True)


# ─── Бэкенд 1: InsightFace InSwapper ─────────────────────────────────────────

class InsightFaceSwapper:
    """
    Нейросетевой face swap через insightface.model_zoo.get_model('inswapper_128').
    Требует скачанную модель (~500 MB) в ~/.insightface/models/inswapper_128.onnx
    """

    def __init__(self, detector: FaceDetector, providers: list[str] | None = None):
        self._detector = detector
        self._swapper  = None
        try:
            import insightface
            self._swapper = insightface.model_zoo.get_model(
                "inswapper_128.onnx",
                providers=providers or ["CPUExecutionProvider"],
            )
            logger.info("InSwapper модель загружена.")
        except Exception as exc:
            logger.warning("Не удалось загрузить InSwapper: %s", exc)

    def swap(
        self,
        source_img: np.ndarray,
        target_img: np.ndarray,
    ) -> Optional[np.ndarray]:
        """
        Заменяет все лица на target_img лицом из source_img.
        Возвращает итоговое изображение или None при ошибке.
        """
        if self._swapper is None or not self._detector.available:
            return None

        source_faces = self._detector.get_faces(source_img)
        if not source_faces:
            logger.warning("Лицо не найдено в source_img.")
            return None

        target_faces = self._detector.get_faces(target_img)
        if not target_faces:
            logger.warning("Лицо не найдено в target_img.")
            return None

        source_face = source_faces[0]  # берём первое (наибольшее) лицо
        result      = target_img.copy()

        for face in target_faces:
            result = self._swapper.get(result, face, source_face, paste_back=True)

        return result


# ─── Бэкенд 2: простая вставка без нейросети ────────────────────────────────

class SimplePasteSwapper:
    """
    Fallback-бэкенд: вырезает лицо из source, ресайзит и вставляет
    в заданные координаты шаблона. Не требует GPU и тяжёлых моделей.
    Используйте только для тестирования пайплайна.
    """

    def __init__(self, detector: FaceDetector):
        self._detector = detector

    def swap(
        self,
        source_img: np.ndarray,
        target_img: np.ndarray,
        face_region: dict,  # {"x": int, "y": int, "w": int, "h": int}
    ) -> Optional[np.ndarray]:
        source_faces = self._detector.get_faces(source_img) if self._detector.available else []

        if source_faces:
            # Вырезаем bbox лица
            b = source_faces[0].bbox.astype(int)
            face_crop = source_img[b[1]:b[3], b[0]:b[2]]
        else:
            # Если детектор недоступен — берём центральную часть изображения
            h, w = source_img.shape[:2]
            margin = int(min(h, w) * 0.15)
            face_crop = source_img[margin:h - margin, margin:w - margin]

        x, y, fw, fh = face_region["x"], face_region["y"], face_region["w"], face_region["h"]
        face_resized = cv2.resize(face_crop, (fw, fh))

        result = target_img.copy()
        result[y:y + fh, x:x + fw] = face_resized
        return result


# ─── Главный процессор ───────────────────────────────────────────────────────

class FaceSwapProcessor:
    """
    Оркестрирует обработку всех шаблонов для одного пользователя.
    Читает конфиг, применяет выбранный бэкенд, сохраняет готовые стикеры.
    """

    STICKER_SIZE = (512, 512)

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            self._config = json.load(f)

        backend   = self._config.get("backend", "insightface")
        providers = self._config.get("onnx_providers", ["CPUExecutionProvider"])

        self._detector = FaceDetector(providers=providers)
        self._output_dir = Path(self._config.get("output_dir", "/tmp/stickers"))
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Инициализируем нужный бэкенд
        if backend == "insightface":
            self._swapper = InsightFaceSwapper(self._detector, providers)
            self._backend = "insightface"
        else:
            self._swapper = SimplePasteSwapper(self._detector)
            self._backend = "simple"

        logger.info("Процессор инициализирован. Бэкенд: %s", self._backend)

    # ── Публичный метод ──────────────────────────────────────────────────────

    def process_all_templates(self, source_path: Path, user_id: int) -> list[str]:
        """
        Применяет face swap ко всем шаблонам из конфига.
        Возвращает список путей к готовым PNG-файлам (512×512).
        Вызывается из executor'а (синхронный контекст).
        """
        source_img = cv2.imread(str(source_path))
        if source_img is None:
            logger.error("Не удалось прочитать файл: %s", source_path)
            return []

        output_paths: list[str] = []

        for template_cfg in self._config.get("templates", []):
            result = self._process_single(source_img, template_cfg)
            if result is None:
                continue

            out_name = f"{user_id}_{uuid.uuid4().hex}.png"
            out_path = self._output_dir / out_name
            cv2.imwrite(str(out_path), result)
            output_paths.append(str(out_path))
            logger.debug("Стикер сохранён: %s", out_path)

        logger.info("Обработано %d стикеров для user_id=%s", len(output_paths), user_id)
        return output_paths

    # ── Приватные методы ─────────────────────────────────────────────────────

    def _process_single(self, source_img: np.ndarray, template_cfg: dict) -> Optional[np.ndarray]:
        """Обрабатывает один шаблон и возвращает готовое 512×512 изображение."""
        tpl_path = Path(template_cfg["path"])
        if not tpl_path.exists():
            logger.warning("Шаблон не найден: %s", tpl_path)
            return None

        target_img = cv2.imread(str(tpl_path), cv2.IMREAD_UNCHANGED)
        if target_img is None:
            logger.warning("Не удалось открыть шаблон: %s", tpl_path)
            return None

        # Если шаблон с альфа-каналом (RGBA), конвертируем для обработки
        has_alpha = (target_img.shape[2] == 4)
        if has_alpha:
            alpha_channel = target_img[:, :, 3]
            target_bgr    = target_img[:, :, :3]
        else:
            alpha_channel = None
            target_bgr    = target_img

        # ── Выполняем swap ───────────────────────────────────────────────────
        face_region = template_cfg.get("face_region")  # {"x","y","w","h"}

        if self._backend == "insightface":
            swapped = self._swapper.swap(source_img, target_bgr)
        else:
            if face_region is None:
                logger.warning("Для 'simple' бэкенда нужна face_region в конфиге: %s", tpl_path)
                return None
            swapped = self._swapper.swap(source_img, target_bgr, face_region)

        if swapped is None:
            return None

        # ── Восстанавливаем альфа-канал ──────────────────────────────────────
        if has_alpha and alpha_channel is not None:
            swapped = cv2.merge([swapped[:, :, 0],
                                 swapped[:, :, 1],
                                 swapped[:, :, 2],
                                 alpha_channel])

        # ── Resize до 512×512 ────────────────────────────────────────────────
        final = self._to_sticker_size(swapped)
        return final

    @classmethod
    def _to_sticker_size(cls, img: np.ndarray) -> np.ndarray:
        """
        Масштабирует изображение до 512×512 с сохранением пропорций
        и добавлением прозрачных полей (letterbox).
        """
        h, w = img.shape[:2]
        scale = min(cls.STICKER_SIZE[0] / h, cls.STICKER_SIZE[1] / w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        # Создаём прозрачный холст 512×512
        has_alpha = (img.ndim == 3 and img.shape[2] == 4)
        canvas = np.zeros((*cls.STICKER_SIZE, 4 if has_alpha else 3), dtype=np.uint8)

        if not has_alpha:
            # Белый фон для RGB-стикеров
            canvas[:] = 255
            canvas = canvas[:, :, :3]

        pad_y = (cls.STICKER_SIZE[0] - new_h) // 2
        pad_x = (cls.STICKER_SIZE[1] - new_w) // 2
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized

        return canvas
