import os
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import fal_client

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FAL_KEY = os.getenv("FAL_KEY")
os.environ["FAL_KEY"] = FAL_KEY or ""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Простое хранилище последних фото пользователей
user_photos = {}

@dp.message(CommandStart())
async def start(message: Message):
    user_photos.pop(message.from_user.id, None)
    await message.answer(
        "Привет! Отправь фото человека, на котором нужно сменить одежду."
    )

@dp.message(Command("cancel"))
async def cancel(message: Message):
    user_photos.pop(message.from_user.id, None)
    await message.answer("Отменено. Отправь новое фото человека.")

@dp.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    photo = message.photo[-1]
    
    try:
        await message.answer("Фото получено, загружаю...")
        
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        url = fal_client.upload(file_bytes.read(), f"{user_id}.jpg")
        
        # Если у пользователя ещё нет фото человека — сохраняем как person
        if user_id not in user_photos:
            user_photos[user_id] = {"person": url}
            await message.answer("Фото человека сохранено.\nТеперь пришли фото одежды или напиши текстом, во что переодеть.")
        else:
            # Это фото одежды
            person_url = user_photos[user_id]["person"]
            await message.answer("Генерирую примерку, подожди 30–70 секунд...")
            
            result = fal_client.subscribe(
                "fal-ai/cat-vton",
                arguments={
                    "human_image_url": person_url,
                    "garment_image_url": url,
                    "cloth_type": "upper",
                    "num_inference_steps": 30,
                    "guidance_scale": 2.5,
                },
                with_logs=False,
            )
            
            await message.answer_photo(result["image"]["url"], caption="Готово!")
            user_photos.pop(user_id, None)
            await message.answer("Можешь отправить новое фото человека.")
            
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer(f"Произошла ошибка: {e}")

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    
    if user_id not in user_photos or "person" not in user_photos[user_id]:
        await message.answer("Сначала отправь фото человека.")
        return
    
    prompt = message.text.strip()
    person_url = user_photos[user_id]["person"]
    
    try:
        await message.answer("Меняю одежду по описанию, подожди...")
        
        full_prompt = f"Change the clothing of the person to: {prompt}. Keep the same face, body, pose and background. Photorealistic."
        
        result = fal_client.subscribe(
            "fal-ai/flux/dev",
            arguments={
                "prompt": full_prompt,
                "image_url": person_url,
                "strength": 0.7,
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
            },
            with_logs=False,
        )
        
        await message.answer_photo(result["images"][0]["url"], caption=f"Готово!\n{prompt}")
        user_photos.pop(user_id, None)
        await message.answer("Можешь отправить новое фото человека.")
        
    except Exception as e:
        logger.error(f"Ошибка текста: {e}")
        await message.answer(f"Ошибка: {e}")

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
