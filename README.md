# asynctkinter
Integrate python's built-in tkinter library with the asyncio framework. This module also contains a simple
workaround to bypass tkinter's master-child-window restrictions (that you always have to have exactly one root window).

## Installation
Just copy the "asynctkinter.py" file into your project and import it.
This module only works for Python 3.

## Usage
Basic usage is simple:
```python3
import asyncio
import asynctkinter as atk


async def my_background_task():
  while True:
    print("This runs too, concurrently!")
    await asyncio.sleep(1)


async def main():
  asyncio.create_task(my_background_taks())

  win = atk.Tk(title="My Window!")
  await win.mainloop()


asyncio.run(main())

```

Asynctkinter also contains some utilities for custom events and asynchronous callbacks. Just take a look at the source code, it's all well documentated and clear and contains more usage examples.
