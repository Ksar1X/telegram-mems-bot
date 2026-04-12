import logging
import os
import cv2
import numpy as np
import subprocess
from pathlib import Path
from PIL import Image, ImageSequence
import insightface

logger = logging.getLogger(__name__)


class FaceSwapProcessor:
    def __init__(self, templates_config):
        if isinstance(templates_config, dict) and "templates" in templates_config:
            self.templates = templates_config["templates"]
        else:
            self.templates = templates_config

        model_path = os.path.expanduser("~/.insightface/models/inswapper_128.onnx")

        self._app = insightface.app.FaceAnalysis(name="buffalo_l", providers=['CPUExecutionProvider'])
        self._app.prepare(ctx_id=-1, det_size=(640, 640))

        if os.path.exists(model_path):
            self._swapper = insightface.model_zoo.get_model(model_path, download=False)
            logger.info("InSwapper успешно загружен.")
        else:
            self._swapper = None
            logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: Модель не найдена: {model_path}")

    def process_all_templates(self, source_path: Path, user_id: int) -> list[str]:
        output_paths = []

        source_img = cv2.imread(str(source_path))
        if source_img is None:
            logger.error(f"Не удалось прочитать фото: {source_path}")
            return []

        source_faces = self._app.get(source_img)
        if not source_faces:
            logger.warning(f"Лицо не найдено на фото пользователя {user_id}")
            return []

        source_face = sorted(source_faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))[-1]

        for tpl in self.templates:
            # ПРОВЕРКА: если tpl - это просто строка (путь), превращаем её в нужный формат
            if isinstance(tpl, str):
                tpl_path = Path(tpl)
                tpl_id = tpl_path.stem
                tpl_emoji = "✨"# Берем имя файла без расширения как ID
            else:
                # Если tpl - это словарь (как мы планировали ранее)
                tpl_path = Path(tpl.get("path", ""))
                tpl_id = tpl.get("id", "unknown")
                tpl_emoji = tpl.get("emoji", "✨")

            if not tpl_path.exists():
                logger.warning(f"Файл шаблона не найден: {tpl_path}")
                continue

            ext = tpl_path.suffix.lower()
            os.makedirs("temp_stickers", exist_ok=True)

            final_ext = ".webm" if ext == ".gif" else ".png"
            output_filename = f"temp_stickers/{user_id}_{tpl_id}{final_ext}"

            try:
                if ext == ".gif":
                    logger.info(f">>> Обработка GIF -> WEBM: {tpl_id}")
                    res_path = self._process_gif_to_webm(source_face, tpl_path, output_filename)
                else:
                    logger.info(f">>> Обработка фото: {tpl_id}")
                    res_path = self._process_image(source_face, tpl_path, output_filename)

                if res_path:
                    output_paths.append({
                        "path": res_path,
                        "emoji": tpl_emoji
                    })
            except Exception as e:
                logger.exception(f"Ошибка при обработке шаблона {tpl_id}: {e}")

        return output_paths

    def _process_image(self, source_face, target_path, output_path):
        """Замена лица на статичном изображении."""
        target_img = cv2.imread(str(target_path))
        faces = self._app.get(target_img)
        if not faces:
            return None

        # Берем самое крупное лицо в шаблоне
        target_face = sorted(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))[-1]

        result = self._swapper.get(target_img, target_face, source_face, paste_back=True)
        result = cv2.resize(result, (512, 512))
        cv2.imwrite(output_path, result)
        return output_path

    def _process_gif_to_webm(self, source_face, target_path, output_path):
        """Покадровая замена лица в GIF с конвертацией в видео-стикер WEBM."""
        temp_gif = output_path.replace(".webm", "_temp.gif")
        try:
            with Image.open(target_path) as im:
                duration = im.info.get('duration', 100)
                # Вычисляем FPS для FFmpeg
                fps = 1000 / duration if duration > 0 else 20

                frames = []
                # Ограничиваем до 60 кадров (примерно 3 сек при 20 FPS)
                all_frames = [f.convert("RGB") for f in ImageSequence.Iterator(im)][:30]

                last_target_face = None
                for frame_pil in all_frames:
                    # Создаем копию массива кадра для OpenCV
                    frame_cv = cv2.cvtColor(np.array(frame_pil), cv2.COLOR_RGB2BGR).copy()

                    faces = self._app.get(frame_cv)
                    if faces:
                        # Находим самое крупное лицо на кадре
                        last_target_face = \
                        sorted(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))[-1]

                    if last_target_face:
                        # Применяем замену (используем последнее найденное лицо, если на этом кадре детекция сбоит)
                        frame_cv = self._swapper.get(frame_cv, last_target_face, source_face, paste_back=True)

                    # Возвращаем в PIL формат
                    res_rgb = cv2.cvtColor(frame_cv, cv2.COLOR_BGR2RGB)
                    frames.append(Image.fromarray(res_rgb).resize((512, 512)))

                if not frames:
                    return None

                # Сохраняем временную гифку
                frames[0].save(
                    temp_gif,
                    save_all=True,
                    append_images=frames[1:],
                    duration=duration,
                    loop=0,
                    disposal=2
                )

            # Освобождаем ресурсы перед вызовом FFmpeg
            del frames

            # Команда FFmpeg для создания WEBM VP9 (требование Telegram)
            # Ограничиваем битрейт и размер, чтобы влезть в 256 Кб
            cmd = [
                'ffmpeg', '-y', '-i', temp_gif,
                '-t', '3',  # Обрезка до 3 секунд
                '-c:v', 'libvpx-vp9',
                '-pix_fmt', 'yuva420p',
                '-crf', '35',  # Качество (30-40 оптимально)
                '-b:v', '500k',  # Битрейт
                '-vf', f'fps={fps},scale=512:512',
                '-an',  # Убираем звук
                output_path
            ]

            # Запуск конвертации (shell=True нужен для Windows)
            subprocess.run(cmd, capture_output=True, text=True, shell=True)

            # Безопасное удаление временного файла (фикс WinError 32)
            if os.path.exists(temp_gif):
                try:
                    os.remove(temp_gif)
                except OSError:
                    pass

            return output_path if os.path.exists(output_path) else None

        except Exception as e:
            logger.error(f"Ошибка при обработке GIF: {e}")
            return None