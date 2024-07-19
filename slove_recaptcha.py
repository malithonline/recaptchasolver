import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import aiohttp
import aiofiles
import os
import tempfile
import speech_recognition as sr
from pydub import AudioSegment
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def download_file(url, file_path):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    async with aiofiles.open(file_path, mode='wb') as f:
                        await f.write(await response.read())
                    return True
                else:
                    logger.error(f"Failed to download file. Status code: {response.status}")
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
    return False

async def convert_mp3_to_wav(mp3_path, wav_path):
    try:
        audio = AudioSegment.from_mp3(mp3_path)
        audio.export(wav_path, format="wav")
    except Exception as e:
        logger.error(f"Error converting MP3 to WAV: {e}")

async def transcribe_audio(file_path):
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(file_path) as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio)
        logger.info(f"Transcription: {text}")
        return text
    except sr.UnknownValueError:
        logger.error("Google Speech Recognition could not understand audio")
    except sr.RequestError as e:
        logger.error(f"Could not request results from Google Speech Recognition service; {e}")
    except Exception as e:
        logger.error(f"Error transcribing audio: {e}")
    return ''

async def solve_recaptcha(page):
    try:
        # Switch to the reCAPTCHA frame
        frame = page.frame_locator('iframe[src^="https://www.google.com/recaptcha/api2/anchor"]')
        await frame.locator('.recaptcha-checkbox-border').click()
        logger.info("Clicked reCAPTCHA checkbox")
        
        # Wait for audio challenge
        await page.wait_for_timeout(2000)
        frame = page.frame_locator('iframe[title="recaptcha challenge expires in two minutes"]')
        await frame.locator('#recaptcha-audio-button').click()
        logger.info("Clicked audio challenge button")
        
        while True:
            try:
                # Get audio source
                audio_source = await frame.locator('#audio-source').get_attribute('src')
                logger.info(f"Audio source found: {audio_source}")
                
                # Download and process audio
                with tempfile.TemporaryDirectory() as temp_dir:
                    mp3_path = os.path.join(temp_dir, 'audio.mp3')
                    wav_path = os.path.join(temp_dir, 'audio.wav')
                    
                    if await download_file(audio_source, mp3_path):
                        logger.info(f"Audio file downloaded to {mp3_path}")
                        await convert_mp3_to_wav(mp3_path, wav_path)
                        
                        if os.path.exists(wav_path):
                            transcription = await transcribe_audio(wav_path)
                            
                            if transcription:
                                logger.info(f"Entering transcription: {transcription}")
                                # Enter the transcription
                                await frame.locator('#audio-response').fill(transcription)
                                await frame.locator('#recaptcha-verify-button').click()
                                logger.info("Submitted transcription")
                                
                                # Check if solved
                                try:
                                    await frame.locator('.rc-audiochallenge-error-message').wait_for(timeout=5000)
                                    logger.warning("reCAPTCHA not solved, trying again")
                                except PlaywrightTimeoutError:
                                    logger.info("reCAPTCHA solved successfully!")
                                    return True
                            else:
                                logger.warning("Transcription failed")
                        else:
                            logger.error("WAV file not created")
                    else:
                        logger.error("Failed to download audio file")
            except Exception as e:
                logger.error(f"Error in solve_recaptcha loop: {e}")
                return False
    except Exception as e:
        logger.error(f"Error in solve_recaptcha: {e}")
        return False

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto('https://www.google.com/recaptcha/api2/demo')
        
        if await solve_recaptcha(page):
            logger.info("reCAPTCHA solved successfully!")
        else:
            logger.error("Failed to solve reCAPTCHA")
        
        await page.wait_for_timeout(5000)  # Keep the browser open for 5 seconds
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())