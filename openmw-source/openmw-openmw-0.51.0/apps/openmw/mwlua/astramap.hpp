// Compiled once by mapwindow.cpp. Controls only the ordinary rendered map UI.
#pragma once
#include <algorithm>
#include <cmath>
#include <functional>

namespace MWGui
{
    std::pair<float, float> MapWindow::astraZoomRange() const
    {
        const auto* map = Settings::map().mGlobal ? mGlobalMap : mLocalMap;
        const auto view = map->getViewCoord();
        float minimum;
        if (Settings::map().mGlobal)
            minimum = std::min(float(view.width) / std::max(1, mGlobalMapRender->getWidth()),
                float(view.height) / std::max(1, mGlobalMapRender->getHeight()));
        else
        {
            const float tile = Settings::map().mLocalMapWidgetSize;
            minimum = std::max({float(Settings::map().mGlobalMapCellSize) * 4.f / tile,
                view.width / (tile * (mGrid.width() + 1)), view.height / (tile * (mGrid.height() + 1))});
        }
        minimum = std::max(0.001f, minimum);
        return {minimum, std::max(4.f, minimum)};
    }

    void MapWindow::astraRestoreMapView()
    {
        if (!mAstraMapFullscreen) return;
        mMainWidget->setCoord(mAstraMapWindow);
        mMainWidget->setUserString("AstraTemporaryFullscreen", "");
        mAstraMapFullscreen = false;
    }

    bool MapWindow::astraMapControl(const std::string& action, float dx, float dy, float factor, bool fit)
    {
        if (action == "windowed" || action == "close")
        {
            astraRestoreMapView();
            return false;
        }
        if (action == "local" || action == "world")
        {
            if (!mAstraMapFullscreen)
            {
                mAstraMapWindow = mMainWidget->getCoord();
                mAstraMapFullscreen = true;
                mMainWidget->setUserString("AstraTemporaryFullscreen", "true");
            }
            const auto size = MyGUI::RenderManager::getInstance().getViewSize();
            mMainWidget->setCoord(0, 0, size.width, size.height);
            if (Settings::map().mGlobal != (action == "world")) onWorldButtonClicked(nullptr);
            const auto [minimum, maximum] = astraZoomRange();
            if (action == "world") { mGlobalMapZoom = minimum; updateGlobalMap(); }
            else { mLocalMapZoom = std::clamp(1.f, minimum, maximum); updateLocalMap(); }
            centerView();
            mNeedDoorMarkersUpdate = true;
            return false;
        }
        auto* map = Settings::map().mGlobal ? mGlobalMap : mLocalMap;
        const auto view = map->getViewCoord();
        const auto before = map->getViewOffset();
        if (action == "pan")
        {
            const auto requested = MyGUI::IntPoint(before.left - int(std::round(dx * view.width)),
                before.top - int(std::round(dy * view.height)));
            map->setViewOffset(requested);
            mNeedDoorMarkersUpdate = true;
            return map->getViewOffset() != requested;
        }
        if (action == "center") { centerView(); mNeedDoorMarkersUpdate = true; }
        if (action == "zoom")
        {
            float& zoom = Settings::map().mGlobal ? mGlobalMapZoom : mLocalMapZoom;
            const auto [minimum, maximum] = astraZoomRange();
            const float old = zoom, requested = fit ? minimum : old * factor;
            zoom = std::clamp(requested, minimum, maximum);
            if (Settings::map().mGlobal) updateGlobalMap(); else updateLocalMap();
            map->setViewOffset(MyGUI::IntPoint(
                int(std::round((before.left - view.width * .5f) * zoom / old + view.width * .5f)),
                int(std::round((before.top - view.height * .5f) * zoom / old + view.height * .5f))));
            mNeedDoorMarkersUpdate = true;
            return std::abs(zoom - requested) > 0.00001f;
        }
        return false;
    }

    MapWindow::AstraMapView MapWindow::astraMapView() const
    {
        AstraMapView out;
        const bool global = Settings::map().mGlobal;
        auto* map = global ? mGlobalMap : mLocalMap;
        out.world = global; out.fullscreen = mAstraMapFullscreen;
        out.zoom = global ? mGlobalMapZoom : mLocalMapZoom;
        const auto [minimum, maximum] = astraZoomRange();
        out.minZoom = minimum; out.maxZoom = maximum;
        const auto view = map->getViewCoord();
        const auto canvas = map->getCanvasSize();
        const auto offset = map->getViewOffset();
        out.left = offset.left < 0; out.up = offset.top < 0;
        out.right = canvas.width > view.width && offset.left > view.width - canvas.width;
        out.down = canvas.height > view.height && offset.top > view.height - canvas.height;
        const auto origin = map->getAbsolutePosition();
        const auto screen = MyGUI::RenderManager::getInstance().getViewSize();
        const MyGUI::IntRect clip(std::max(0, origin.left + view.left), std::max(0, origin.top + view.top),
            std::min(screen.width, origin.left + view.right()), std::min(screen.height, origin.top + view.bottom()));
        auto plain = [](std::string_view text) {
            return MyGUI::TextIterator::getOnlyText(MyGUI::LanguageManager::getInstance().replaceTags(std::string(text))).asUTF8();
        };
        std::function<void(MyGUI::Widget*)> visit = [&](MyGUI::Widget* widget) {
            if (!widget->getInheritedVisible() || widget->getAlpha() <= 0) return;
            const auto rect = widget->getAbsoluteRect();
            if (rect.right <= clip.left || rect.left >= clip.right || rect.bottom <= clip.top || rect.top >= clip.bottom) return;
            const auto& type = widget->getUserString("ToolTipType");
            AstraMapMarker marker;
            if (type == "MapMarker")
            {
                const auto* data = widget->getUserData<LocalMapBase::MarkerUserData>(false);
                // Identical to ToolTips::onFrame: the widget can exist beneath fog.
                if (!data || !data->isPositionExplored()) return;
                marker.text = plain(data->caption);
                for (const auto& note : data->notes)
                { if (!marker.notes.empty()) marker.notes += '\n'; marker.notes += plain(note); }
            }
            else if (type == "Layout" && widget->getUserString("ToolTipLayout") == "TextToolTipOneLine")
                marker.text = plain(widget->getUserString("Caption_TextOneLine"));
            if (!marker.text.empty() || !marker.notes.empty())
            {
                marker.x = (std::max(rect.left, clip.left) + std::min(rect.right, clip.right)) * .5f / screen.width;
                marker.y = (std::max(rect.top, clip.top) + std::min(rect.bottom, clip.bottom)) * .5f / screen.height;
                out.markers.push_back(std::move(marker));
            }
            auto children = widget->getEnumerator();
            while (children.next()) visit(children.current());
        };
        visit(map);
        std::sort(out.markers.begin(), out.markers.end(), [](const auto& a, const auto& b) {
            return a.y != b.y ? a.y < b.y : a.x < b.x;
        });
        return out;
    }
}
