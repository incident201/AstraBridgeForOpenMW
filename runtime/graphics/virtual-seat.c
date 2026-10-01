/* SPDX-License-Identifier: GPL-3.0-or-later
 * A virtual seat for Weston 13's headless backend. No host input devices.
 * Built against the exact libweston ABI shipped in the runtime image.
 */
#include <libweston/libweston.h>
#include <stdlib.h>

/* Exported libweston 13 backend entry points, not in its installed public header. */
void weston_seat_init(struct weston_seat *, struct weston_compositor *, const char *);
int weston_seat_init_pointer(struct weston_seat *);
int weston_seat_init_keyboard(struct weston_seat *, struct xkb_keymap *);
void weston_seat_release(struct weston_seat *);

struct astra_seat {
    struct weston_seat seat;
    struct wl_listener destroy;
};

static void destroy_seat(struct wl_listener *listener, void *unused)
{
    (void)unused;
    struct astra_seat *state = wl_container_of(listener, state, destroy);
    wl_list_remove(&state->destroy.link);
    weston_seat_release(&state->seat);
    free(state);
}

WL_EXPORT int wet_module_init(struct weston_compositor *compositor, int *argc, char *argv[])
{
    (void)argc;
    (void)argv;
    if (!wl_list_empty(&compositor->seat_list))
        return 0;
    struct astra_seat *state = calloc(1, sizeof(*state));
    if (!state)
        return -1;
    weston_seat_init(&state->seat, compositor, "astrabridge");
    if (weston_seat_init_pointer(&state->seat) < 0 || weston_seat_init_keyboard(&state->seat, NULL) < 0) {
        weston_seat_release(&state->seat);
        free(state);
        return -1;
    }
    state->destroy.notify = destroy_seat;
    wl_signal_add(&compositor->destroy_signal, &state->destroy);
    return 0;
}
