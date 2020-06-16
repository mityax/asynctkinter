"""
This module integrates python's standard GUI-module tkinter
with the asyncio framework. Additionally, it contains a
workaround to bypass tkinter's restrictions/constraints in terms
of multiple window support.

See the documentation of the "Tk" class for more information
and usage examples.
"""


import asyncio
import queue
import time
from typing import Callable, Coroutine, Any, Union

try:
    from tkinter import *
except ImportError:
    print("The tkinter module for python3.8 is not installed. Usually, it\n"
          "belongs to the standard library of python, but some distributions (e. g. Ubuntu)\n"
          "do not include it. On most unix-like systems, it can simply be\n"
          "installed through the default package manager. The package name is\n"
          "usually \"python3.8-tk\".")
    exit(1)


# Tkinter always creates one "root" window - the following two lines hide it,
# so it does not annoy the user. This is part of the multiple-window-workaround.
# Note: We do not make this variable completely private, as there are some cases
# the user could profit of having access to it.
_master_tk = Tk()
_master_tk.withdraw()


class AsyncEventDispatcher:
    """
    Simple interface for binding and unbinding callback functions to events.
    Multiple callbacks per event are supported. Coroutines (async def) and
    normal functions (def) are supported.
    """

    def __init__(self):
        self.__callbacks = {}

    def on(self, event_name: str, callback: Callable[[], Any], before: bool = False):
        """
        Registers a new event listener. The listener is called after any previously
        registered listener, unless `before` is True, in which case it is called
        before any previously registered callback.

        If the callback returns a value that bool(x) returns True for, all remaining
        callbacks are ignored.
        Callback can be either an async def (coroutine) or a normal python function.

        :param event_name: The name of the event to listen for
        :param callback: The function to be called when the event occurs
        :param before: Whether to call the callback before or after all already set callbacks
        """

        if event_name not in self.__callbacks:
            self.__callbacks[event_name] = []

        if before:
            self.__callbacks[event_name].insert(0, callback)
        else:
            self.__callbacks[event_name].append(callback)

    def off(self, event_name_or_callback: Union[str, Callable[[], Any]]) -> bool:
        """
        Unregisters a callback registered with the EventDispatcher.on() method.

        If `event_name_or_callback` is a string, all callbacks registered for the
        event whose name matches the string's value are unregistered.
        If `event_name_or_callback` is a function, it will be unregistered for any
        event is has been registered for, if any.

        :param event_name_or_callback: Specify what callback(s) to unregister.
        :return True if eny callback has been unregistered, False otherwise
        """

        if isinstance(event_name_or_callback, str):
            if event_name_or_callback in self.__callbacks:
                del self.__callbacks[event_name_or_callback]
                return True
            return False
        else:
            has_unregistered = True
            for v in self.__callbacks.values():
                if event_name_or_callback in v:
                    v.remove(event_name_or_callback)
                    has_unregistered = True
            return has_unregistered

    async def dispatch(self, event_name: str, *args, **kwargs) -> Any:
        """
        Calls all registered callbacks for the given event.

        :param event_name: The event's name
        :param args: Additional arguments to pass to callbacks
        :param kwargs: Additional keyword-arguments to pass to callbacks
        :return The return value of the last callback that has been called, or None
        """

        if event_name not in self.__callbacks or not self.__callbacks[event_name]:
            return

        res = None
        for cb in self.__callbacks[event_name]:
            res = cb(*args, **kwargs)
            if asyncio.iscoroutine(res):
                res = await res

            if res:
                break
        return res


class Tk(Toplevel, AsyncEventDispatcher):
    """
    A tkinter.TK alternative intended to integrate with the asyncio eco system.
    See the Tk.mainloop() method for detailed information and a usage example.

    This class inherits from AsyncEventDispatcher and therefore dispatches the
    following events:

        "close" - when the window is going to be closed, using either .destroy() or .quit()
                  methods
        "quit" - when the .quit() method is called (fired after the "close" event)
        "destroy" - when the .destroy() method is called (fired after the "close" event)

    The 'destroy' and 'quit' events are bound to close the window automatically
    by default. If you do not want this behaviour, simply prevent those callbacks
    from being called automatically, e.g. by specifying a callback before them.
    See the "AsyncEventDispatcher" class for more details.

    The "close" event provides a combined interface for "destroy" and "quit", e. g.:

    def my_callback():
        if not messagebox.askokcancel("Quit", "Do you really want to quit?"):
            # Prevent the default "destroy" or "quit" callbacks from being called:
            return True

    my_win.on("close", my_callback)

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        AsyncEventDispatcher.__init__(self)

        # Scheduled tasks to run in the mainloop
        self.__scheduled_tasks = queue.Queue()

        # Internal variable to stop the mainloop
        self.__is_closed = False

        # bind default event handlers:
        self.on('close', super().withdraw)
        self.on('destroy', super().destroy)
        self.on('quit', super().quit)

        # Route window manager close event to default event handlers:
        self.protocol("WM_DELETE_WINDOW", self.async_callback(self.destroy))

    async def mainloop(self, fps: float = 25):
        """
        An asynchronous implementation of the  Tk.mainloop()  function to
        integrate with asyncio and avoid the overhead of using multiple threads.

        Use this function like this:


        async def my_main_function():
            # Do fancy async stuff in here.
            await asyncio.sleep(5)
            my_win.destroy()

        my_win = asynctkinter.Tk()

        asnycio.run(asyncio.gather(my_main_function(), my_win.mainloop()))


        :param fps: The maximum times per second to update the user interface.
        """

        update_interval = 1 / fps

        while True:
            # Monitor how long the frame takes
            start_time = time.time()

            try:
                # The original tkinter mainloop function basically just calls this
                # function repeatedly:
                self.update()
            except TclError:
                # The window has been destroyed
                break

            if self.__is_closed:
                break

            await self.__call_scheduled_tasks()

            # Sleep the remaining frame interval and let asyncio execute other tasks
            sleep_time = update_interval - (time.time() - start_time)
            # Always wait a minimal amount of time to ensure that the UI does not block all other asyncio tasks
            # on (really) slow systems. On modern desktop computers and with  max_fps  set to 25,  sleep_time  is
            # usually about 70 times as long as the below minimum (0.005):
            sleep_time = max(0.005, sleep_time)

            await asyncio.sleep(sleep_time)

    async def __call_scheduled_tasks(self):
        """
        Internal method to call all the tasks scheduled with  .schedule() .
        """

        while not self.__scheduled_tasks.empty():
            cb, args, kwargs = self.__scheduled_tasks.get()
            res = cb(*args, **kwargs)
            if asyncio.iscoroutinefunction(cb):
                await res

    async def destroy(self):
        """
        Overrides the default tkinter method to make asynctkinter.Tk.mainloop() aware
        that the mainloop shall be quit.
        """

        if not await self.dispatch('close'):
            self.__is_closed = True
            await self.dispatch('destroy')

    async def quit(self):
        """
        Overrides the default tkinter method to make asynctkinter.Tk.mainloop() aware
        that the mainloop shall be quit.
        """

        if not await self.dispatch('close'):
            self.__is_closed = True
            await self.dispatch('quit')

    def schedule(self, task: Callable[..., Coroutine], *args, **kwargs):
        """
        Schedules an async coroutine (async def) or a normal python function for
        future execution in the UI task, therefore blocking the UI from being updated
        while the callback is running.

        :param task: The async callback function
        :param args: Arguments to pass to the function
        :param kwargs: Keyword-arguments to pass to the function
        """

        self.__scheduled_tasks.put_nowait((task, args, kwargs))

    def callback(self, task: Callable[..., Coroutine], *args, **kwargs) -> Callable:
        """
        Does the same as .async_callback() except that callbacks registered using this method
        run on the UI task and therefore block the user interface from being updated while they
        run. Callbacks can either be coroutines (async def) or normal python functions.

        This function can also be used as a decorator to the callback function, but be aware
        that it is not a static method and therefore can only be used when the  TK  instance
        is already available.

        :param task: The callback function to schedule
        :param args: Arguments to pass to the function
        :param kwargs: Keyword-arguments to pass to the function
        """

        return lambda *cb_args, **cb_kwargs: self.schedule(task, *args, *cb_args, **cb_kwargs, **kwargs)

    @staticmethod
    def async_callback(task: Callable[..., Coroutine], *args, **kwargs) -> Callable:
        """
        Shorthand for creating an async callback using asyncio.create_task().
        The callback is not executed in the main task of this window and therefore
        does not block the UI from being updated. If you wish to create a callback
        running on the UI task, you can use the .callback() method.
        Simple usage:


        async def my_async_callback():
            print("Starting callback...")
            await asyncio.sleep(10)
            print("Callback done.")

        my_but = Button(my_tk, "Click me!", command=Tk.async_callback(my_async_callback))


        This function can also be used as a decorator to the callback function:


        @Tk.async_callback
        async def my_async_callback():
            ...

        my_but = Button(my_tk, "Click me!", command=my_async_callback)


        Using this approach however, you lose the ability to pass further arguments to the callback.

        This method avoids the need to put a 'lambda:' before each callback, yielding cleaner and more
        understandable code.
        Also, this method passes on any arguments that a simple, synchronous callback function would
        receive if it was used in place of this. These arguments come after the optional ones passed
        to this method.

        :param task: The async callback function
        :param args: Arguments to pass to the function
        :param kwargs: Keyword-arguments to pass to the function
        """

        return lambda *cb_args, **cb_kwargs: asyncio.create_task(task(*args, *cb_args, **kwargs, **cb_kwargs))
