from typing import Callable, Optional
from binaryninja import BinaryView, PluginCommand, BackgroundTask, BackgroundTaskThread
import binaryninja as bn
from . import msvc
from .types import RelativeOffsetRenderer, RelativeOffsetListener

PLUGIN_NAME = "ReadTheTypesIn"

class Searcher(BackgroundTaskThread):
    def __init__(self, view: BinaryView, func: Callable[[BinaryView, BackgroundTask], None]):
        super().__init__("Searching...", True)
        self.view = view
        self.func = func

    def run(self):
        self.func(self.view, task=self)
        self.view.update_analysis()

def as_task(func: Callable[[BackgroundTask, BinaryView], None]):
    def start(view: BinaryView):
        s = Searcher(view, func)
        s.start()
    return start

msvc.register_renderers()

PluginCommand.register(
    f"{PLUGIN_NAME}\\Search all",
    "Search",
    as_task(msvc.search)
)
