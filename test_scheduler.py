import asyncio
import sys

# Force Windows to use UTF-8 so emojis in print() don't crash
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from scheduler import daily_summary_job, stale_task_check_job

async def main():
    print("Testing Daily Summary Job...")
    await daily_summary_job()
    
    print("\nTesting Stale Task Check Job...")
    await stale_task_check_job()

if __name__ == "__main__":
    asyncio.run(main())

