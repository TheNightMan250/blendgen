"""Modal Blender batch controls; export and geometry stay in separate modules."""

from pathlib import Path

import bpy

from .dataset import ExportSession


TIMER_INTERVAL_SECONDS = 0.1


def is_timer_event(event):
    """Return whether Blender dispatched a window-manager timer tick.

    ``WindowManager.event_timer_add`` returns a Timer handle for lifecycle
    management, but ``bpy.types.Event`` only identifies timer ticks by type.
    Keeping that API detail here makes the modal operator easy to test without
    depending on undocumented Event attributes.
    """
    return event.type == 'TIMER'


class GenerateDataset(bpy.types.Operator):
    bl_idname = 'blendgen_proto.export_dataset'
    bl_label = 'Generate and Save Dataset'
    bl_description = 'Randomize and save clean PNGs, YOLO labels and bounding-box previews'

    session = None
    settings = None
    timer = None

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and not context.window_manager.blendgen_exporting

    def start(self, context):
        from .ui import config

        settings = context.scene.blendgen_proto
        self.session = ExportSession(context, settings, config(settings))
        self.settings = settings
        settings.last_output_directory = str(self.session.output)
        context.window_manager.blendgen_exporting = True
        context.window_manager.blendgen_stop_export = False
        context.window_manager.progress_begin(0, self.session.total)
        settings.status = f'Exporting 0/{self.session.total}'

    def invoke(self, context, event):
        try:
            self.start(context)
            self.timer = context.window_manager.event_timer_add(
                TIMER_INTERVAL_SECONDS,
                window=context.window,
            )
            context.window_manager.modal_handler_add(self)
        except Exception as exc:
            return self.end(context, 'failed', str(exc))
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC' or context.window_manager.blendgen_stop_export:
            return self.end(context, 'cancelled')
        if is_timer_event(event):
            try:
                more = self.session.step()
                context.window_manager.progress_update(self.session.completed)
                self.settings.status = (
                    f'Exporting {self.session.completed}/{self.session.total}'
                )
                if context.area:
                    context.area.tag_redraw()
                if not more:
                    return self.end(context, 'complete')
            except Exception as exc:
                return self.end(context, 'failed', str(exc))
        return {'PASS_THROUGH'}

    def execute(self, context):
        try:
            self.start(context)
            while self.session.step():
                context.window_manager.progress_update(self.session.completed)
                if context.window_manager.blendgen_stop_export:
                    return self.end(context, 'cancelled')
        except Exception as exc:
            return self.end(context, 'failed', str(exc))
        return self.end(context, 'complete')

    def cancel(self, context):
        self.end(context, 'cancelled')

    def end(self, context, status, error=None):
        issues = [error] if error else []
        session = self.session
        if session:
            try:
                session.finish(status, error)
            except Exception as exc:
                issues.append(f'Cannot save run status: {exc}')
            try:
                session.restore()
            except Exception as exc:
                issues.append(f'Cannot restore scene: {exc}')
        if self.timer is not None:
            context.window_manager.event_timer_remove(self.timer)
            self.timer = None
        context.window_manager.progress_end()
        context.window_manager.blendgen_exporting = False
        context.window_manager.blendgen_stop_export = False
        if issues:
            status = 'failed'
        count = session.completed if session else 0
        directory = str(session.output) if session else '(no run created)'
        message = f'{status.title()}: {count} image(s). {directory}'
        if issues:
            message += ' | ' + '; '.join(issues)
        context.scene.blendgen_proto.status = message
        self.report({'ERROR'} if issues else {'INFO'}, message)
        self.session = None
        self.settings = None
        return {'FINISHED'} if status == 'complete' else {'CANCELLED'}


class StopDataset(bpy.types.Operator):
    bl_idname = 'blendgen_proto.stop_export'
    bl_label = 'Stop After Current Image'

    @classmethod
    def poll(cls, context):
        return context.window_manager.blendgen_exporting

    def execute(self, context):
        context.window_manager.blendgen_stop_export = True
        return {'FINISHED'}


class OpenOutput(bpy.types.Operator):
    bl_idname = 'blendgen_proto.open_output'
    bl_label = 'Open Output Folder'

    def execute(self, context):
        settings = context.scene.blendgen_proto
        path = settings.last_output_directory or bpy.path.abspath(
            settings.output_directory
        )
        if not Path(path).is_dir():
            self.report(
                {'ERROR'},
                'No output folder exists yet. Generate a dataset first.',
            )
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=path)
        return {'FINISHED'}


CLASSES = (GenerateDataset, StopDataset, OpenOutput)
