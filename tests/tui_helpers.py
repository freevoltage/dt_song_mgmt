"""Drive widgets through keys, clicks and paste events without mocking sessions."""
from textual.events import Paste
from dt_song_mgmt.tui import EntryModal, ProjectPickerModal, SaveValidationModal
from dt_song_mgmt.tui_patterns import PatternEntryModal, PatternManagerScreen


class TuiDriver:
    def __init__(self, case, pilot, app):
        self.case, self.pilot, self.app = case, pilot, app

    async def fill(self, selector, value):
        await self.pilot.click(selector)
        await self.pilot.press('home', 'shift+end')
        # Simulate a terminal paste into the focused input, not setting its value.
        self.app.focused.post_message(Paste(str(value)))
        await self.pilot.pause()

    async def enter(self, value):
        self.case.assertIsInstance(self.app.screen, (EntryModal, PatternEntryModal))
        selector = '#entry-input' if isinstance(self.app.screen, EntryModal) else '#pattern-entry'
        await self.fill(selector, value)
        await self.pilot.press('enter')
        await self.pilot.pause()

    async def open(self, path):
        await self.pilot.press('ctrl+o')
        self.case.assertIsInstance(self.app.screen, ProjectPickerModal)
        # Select through the actual picker by its filename filter.
        await self.pilot.press('f')
        await self.fill('#project-picker-filter', path.name)
        await self.pilot.press('enter')
        await self.pilot.pause()
        self.case.assertEqual(self.app.session.path, path.resolve())

    async def pattern(self, label):
        self.case.assertIsInstance(self.app.screen, PatternManagerScreen)
        await self.pilot.press('/')
        await self.fill('#pattern-search', label)
        await self.pilot.press('enter')
        index = (ord(label[0]) - ord('A')) * 16 + int(label[1:]) - 1
        self.case.assertEqual(self.app.screen.selected_pattern, index)

    async def mapping(self, destinations):
        for source, destination in destinations.items():
            await self.fill(f'#mapping-destination-{source}', destination)
        await self.pilot.click('#apply')
        await self.pilot.pause()

    async def save(self, path=None):
        await self.pilot.press('s')
        if path is not None:
            await self.enter(path)
        self.case.assertIsInstance(self.app.screen, SaveValidationModal)
        self.case.assertTrue(self.app.screen.can_continue, self.app.screen.checks)
        await self.pilot.click('#continue')
        await self.pilot.pause()
        self.case.assertFalse(self.app.session.operations)

    async def quit(self):
        await self.pilot.press('q')
        await self.pilot.pause()
        self.case.assertFalse(self.app.is_running)
