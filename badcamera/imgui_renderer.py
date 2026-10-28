"""moderngl-window's imgui renderer predates ImGui 1.92's texture API (the only imgui-bundle builds for Python 3.14).
This subclass ports the 1.92 texture handling from imgui_bundle/python_backends/opengl_base_backend.py to moderngl."""
import ctypes

import moderngl
from imgui_bundle import imgui
from moderngl_window.integrations.imgui_bundle import ModernglWindowRenderer


class Renderer(ModernglWindowRenderer):
    def refresh_font_texture(self):
        self.io.backend_flags |= imgui.BackendFlags_.renderer_has_textures

    def _update_textures(self):
        S = imgui.ImTextureStatus
        for tex in imgui.get_platform_io().textures:
            if tex.status == S.want_create:
                t = self.ctx.texture((tex.width, tex.height), 4, tex.get_pixels_array().tobytes())
                self.register_texture(t)
                tex.set_tex_id(t.glo)
                tex.status = S.ok
            elif tex.status == S.want_updates:
                # shortcut: re-uploads the whole atlas instead of tex.updates rects; fine for a few font sizes
                self._textures[tex.tex_id].write(tex.get_pixels_array().tobytes())
                tex.status = S.ok
            elif tex.status == S.want_destroy:
                t = self._textures.pop(tex.tex_id, None)
                if t:
                    t.release()
                tex.set_tex_id(0)
                tex.status = S.destroyed

    def render(self, draw_data):
        self._update_textures()
        io = self.io
        dw, dh = io.display_size
        fb_h = int(dh * io.display_framebuffer_scale[1])
        if dw <= 0 or dh <= 0:
            return
        self.projMat.value = (2.0 / dw, 0, 0, 0, 0, -2.0 / dh, 0, 0, 0, 0, -1.0, 0, -1.0, 1.0, 0, 1.0)
        draw_data.scale_clip_rects(imgui.ImVec2(*io.display_framebuffer_scale))
        self.ctx.enable_only(moderngl.BLEND)
        self.ctx.blend_equation = moderngl.FUNC_ADD
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        for cl in draw_data.cmd_lists:
            self._vertex_buffer.orphan(cl.vtx_buffer.size() * imgui.VERTEX_SIZE)
            self._index_buffer.orphan(cl.idx_buffer.size() * imgui.INDEX_SIZE)
            self._vertex_buffer.write((ctypes.c_byte * (cl.vtx_buffer.size() * imgui.VERTEX_SIZE)).from_address(cl.vtx_buffer.data_address()))
            self._index_buffer.write((ctypes.c_byte * (cl.idx_buffer.size() * imgui.INDEX_SIZE)).from_address(cl.idx_buffer.data_address()))
            for cmd in cl.cmd_buffer:
                self._textures[cmd.tex_ref.get_tex_id()].use(0)
                x, y, z, w = cmd.clip_rect
                self.ctx.scissor = int(x), int(fb_h - w), int(z - x), int(w - y)
                self._vao.render(moderngl.TRIANGLES, vertices=cmd.elem_count, first=cmd.idx_offset)
        self.ctx.scissor = None
        self.ctx.disable(moderngl.BLEND)
