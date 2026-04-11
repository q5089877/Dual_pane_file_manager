from core.interfaces import ITrashView

class TrashPresenter:
    """
    Presenter for the Temporary Trash.
    Coordinates between TrashModel and TrashView.
    """
    def __init__(self, view, model):
        self.view = view
        self.model = model
        
        # Connect model signals to view
        self.model.trash_counter_updated.connect(self.view.set_counter)
        
    def load(self):
        """Initial load and cleanup check."""
        count = self.model.get_count()
        self.view.set_counter(count)
        self.model.check_auto_purge()
        
    def add_paths(self, paths):
        """Adds paths to the temporary trash."""
        self.model.trash_paths(paths)
        
    def on_empty_trash(self):
        """Clears all items in the temporary trash."""
        self.model.clear_all()
