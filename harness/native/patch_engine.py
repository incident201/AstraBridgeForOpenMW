#!/usr/bin/env python3
"""Apply the small, version-pinned UI patch to an unpacked OpenMW 0.51.0 tree."""
from pathlib import Path
import argparse, shutil, re
p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
root=a.source
def replace(path,old,new):
    file=root/path;s=file.read_text()
    if new in s:return
    # Later insertions can split an earlier block. Recognise inserted bindings
    # and includes so reapplying this script does not duplicate them.
    added_apis=set(re.findall(r'api\["(_astra[^\"]+)"\]',new))-set(re.findall(r'api\["(_astra[^\"]+)"\]',old))
    added_includes={line.strip() for line in new.splitlines() if line.strip().startswith('#include ')}-{line.strip() for line in old.splitlines()}
    markers=[f'api["{name}"]' for name in added_apis]+list(added_includes)
    if markers and all(marker in s for marker in markers):return
    if old not in s:raise RuntimeError(f'Unexpected source: {path}')
    file.write_text(s.replace(old,new,1))
def copy_header(name):
    source=Path(__file__).with_name(name);target=root/'apps/openmw/mwlua'/name
    if not target.exists() or target.read_bytes()!=source.read_bytes():shutil.copyfile(source,target)
replace('apps/openmw/mwlua/uibindings.cpp','#include "../mwbase/windowmanager.hpp"',
'''#include "../mwbase/windowmanager.hpp"
#include "astraui.hpp"''')
replace('apps/openmw/mwlua/uibindings.cpp','#include "astraui.hpp"',
'''#include "astraui.hpp"
#include "../mwbase/inputmanager.hpp"
#include "../mwinput/actions.hpp"''')
replace('apps/openmw/mwlua/uibindings.cpp','        sol::table api(lua, sol::create);',
'''        sol::table api(lua, sol::create);
        api["_astraUiSnapshot"] = [context, windowManager](sol::this_state state) {
            if (!context.mLuaManager->isSynchronizedUpdateRunning()) throw std::runtime_error("Astra UI requires onFrame");
            return AstraUI::observe(state, windowManager);
        };
        api["_astraUiChoose"] = [context, windowManager](const std::string& ref) {
            if (!context.mLuaManager->isSynchronizedUpdateRunning()) throw std::runtime_error("Astra UI requires onFrame");
            return AstraUI::choose(windowManager, ref);
        };''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_setHudVisibility"]',
'''        api["_astraActivate"] = [context, windowManager]() {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()
                || windowManager->isGuiMode()) return false;
            MWBase::Environment::get().getInputManager()->executeAction(MWInput::A_Activate);
            return true;
        };
        api["_setHudVisibility"]''')
if 'struct AstraRun' not in (root/'apps/openmw/mwgui/bookpage.hpp').read_text():
    replace('apps/openmw/mwgui/bookpage.hpp','        virtual void setFocusItem(BookTypesetter::Style* itemStyle) = 0;',
'''        virtual void setFocusItem(BookTypesetter::Style* itemStyle) = 0;
        struct AstraRun { std::string text; MyGUI::IntRect rect; TypesetBook::InteractiveId link; };
        virtual std::vector<AstraRun> astraVisibleRuns() const = 0;
        virtual void astraActivateLink(TypesetBook::InteractiveId id) = 0;''')
if 'std::vector<AstraRun> astraVisibleRuns' not in (root/'apps/openmw/mwgui/bookpage.cpp').read_text():
    replace('apps/openmw/mwgui/bookpage.cpp','        void setFocusItem(BookTypesetter::Style* itemStyle) override',
'''        std::vector<AstraRun> astraVisibleRuns() const override
        {
            std::vector<AstraRun> result;
            if (!mPageDisplay || !mPageDisplay->mBook) return result;
            const auto origin = getAbsolutePosition();
            for (const auto& section : mPageDisplay->mBook->mSections)
                for (const auto& line : section.mLines)
                {
                    if (line.mRect.bottom <= mPageDisplay->mViewTop || line.mRect.top >= mPageDisplay->mViewBottom) continue;
                    for (const auto& run : line.mRuns)
                    {
                        std::string text(reinterpret_cast<const char*>(run.mRange.first), reinterpret_cast<const char*>(run.mRange.second));
                        MyGUI::IntRect rect(origin.left+run.mLeft, origin.top+line.mRect.top-mPageDisplay->mViewTop,
                            origin.left+run.mRight, origin.top+line.mRect.bottom-mPageDisplay->mViewTop);
                        result.push_back({std::move(text),rect,run.mStyle->mInteractiveId});
                    }
                }
            return result;
        }
        void astraActivateLink(TypesetBook::InteractiveId id) override
        {
            if (mPageDisplay && mPageDisplay->mLinkClicked) mPageDisplay->mLinkClicked(id);
        }
        void setFocusItem(BookTypesetter::Style* itemStyle) override''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraActivate"]',
'''        api["_astraRest"] = [context, windowManager]() {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()) return false;
            if (windowManager->isGuiMode()) return false;
            MWBase::Environment::get().getInputManager()->executeAction(MWInput::A_Rest);
            return windowManager->containsMode(MWGui::GM_Rest);
        };
        api["_astraActivate"]''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraActivate"]',
'''        api["_astraPlayerState"] = [context](sol::this_state state) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning())
                throw std::runtime_error("Astra player state requires player onFrame");
            return AstraUI::playerState(state);
        };
        api["_astraActivate"]''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraPlayerState"]',
'''        api["_astraUiEdit"] = [context, windowManager](const std::string& ref, const std::string& value) {
            if (!context.mLuaManager->isSynchronizedUpdateRunning()) throw std::runtime_error("Astra UI requires onFrame");
            return AstraUI::edit(windowManager, ref, value);
        };
        api["_astraPlayerState"]''')
copy_header('astraui.hpp')
replace('apps/openmw/mwgui/itemchargeview.hpp','        void update();',
'''        std::vector<ItemWidget*> astraItemWidgets() const
        {
            std::vector<ItemWidget*> result;
            for (const auto& line : mLines) result.push_back(line.mIcon);
            return result;
        }
        void update();''')
for file, variable, body, kind in (
    ('bookwindow.cpp', 'book', 'mLeftPage', 'book'),
    ('scrollwindow.cpp', 'scroll', 'mTextView', 'scroll'),
):
    anchor=f'        m{variable.capitalize()} = {variable};'
    extra='\n        mRightPage->setUserString("AstraDocumentBody", "duplicate");' if kind=='book' else ''
    replace('apps/openmw/mwgui/'+file, anchor, anchor+f'''
        static unsigned long long astraDocumentInstance = 0;
        {body}->setUserString("AstraDocumentBody", "{kind}");
        {body}->setUserString("AstraDocumentTitle", std::string({variable}.getClass().getName({variable})));
        {body}->setUserString("AstraDocumentInstance", std::to_string(++astraDocumentInstance));'''+extra)
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraUiEdit"]',
'''        api["_astraReadDocument"] = [context, windowManager](sol::this_state state,
            const std::string& ref, int offset, int limit) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning())
                throw std::runtime_error("Astra document reading requires player onFrame");
            return AstraUI::read(state, windowManager, ref, offset, limit);
        };
        api["_astraResetNPC"] = [context, windowManager]() {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()
                || windowManager->isGuiMode()) return false;
            // Exact engine implementation of RA/ResetActors, no console or eval.
            MWBase::Environment::get().getWorld()->resetActors();
            return true;
        };
        api["_astraUiEdit"]''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraUiSnapshot"]',
'''        api["_astraDoorDescription"] = [context](const LObject& object) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning())
                throw std::runtime_error("Astra description requires player onFrame");
            return AstraUI::doorDescription(object);
        };
        api["_astraUiSnapshot"]''')
replace('apps/openmw/mwlua/uibindings.cpp','#include "astraui.hpp"',
'''#include "astraui.hpp"
#include "astracombat.hpp"''')
replace('apps/openmw/mwlua/uibindings.cpp','#include "astracombat.hpp"',
'''#include "astracombat.hpp"
#include "../mwworld/datetimemanager.hpp"''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraUiEdit"]',
'''        api["_astraPause"] = [context]() {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()) return false;
            auto time = MWBase::Environment::get().getWorld()->getTimeManager();
            time->pause("AstraBridge");
            // onFrame runs before Engine::frame samples isPaused for world/mechanics.
            // Use the same tagged pause as world.pause, but make it effective now.
            time->updateIsPaused();
            return true;
        };
        api["_astraUiEdit"]''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraUiEdit"]',
'''        api["_astraCombatInfo"] = [context](sol::this_state state) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning())
                throw std::runtime_error("Astra combat info requires player onFrame");
            return AstraCombat::info(state);
        };
        api["_astraSpellInfo"] = [context](sol::this_state state, const std::string& id) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning())
                throw std::runtime_error("Astra spell info requires player onFrame");
            return AstraCombat::spellInfo(state, ESM::RefId::stringRefId(id));
        };
        api["_astraTargetReach"] = [context](sol::this_state state, const LObject& object) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning())
                throw std::runtime_error("Astra reach requires player onFrame");
            return AstraCombat::reach(state, object);
        };
        api["_astraUiEdit"]''')
copy_header('astracombat.hpp')
replace('apps/openmw/mwgui/itemview.hpp','        ItemModel* getModel() { return mModel.get(); }',
'''        ItemModel* getModel() { return mModel.get(); }
        MyGUI::ScrollView* astraScrollView() const { return mScrollView; }''')
replace('apps/openmw/mwgui/trainingwindow.cpp','            button->setUserData(skills[i].first);',
'''            button->setUserString("AstraUnavailableReason", price > playerGold ? "insufficient_gold" : "");
            button->setUserData(skills[i].first);''')
replace('apps/openmw/mwgui/spellbuyingwindow.cpp','        toAdd->setUserData(price);',
'''        toAdd->setUserString("AstraUnavailableReason", price > playerGold ? "insufficient_gold" : "");
        toAdd->setUserData(price);''')
replace('apps/openmw/mwgui/widgets.cpp','            mTextWidget->setCaption("?");',
'''            mTextWidget->setCaption("?");
            setUserString("AstraEffectText", "?");''')
replace('apps/openmw/mwgui/widgets.cpp','        mTextWidget->setCaptionWithReplacing(spellLine);',
'''        mTextWidget->setCaptionWithReplacing(spellLine);
        setUserString("AstraEffectText", mTextWidget->getCaption().asUTF8());''')
replace('apps/openmw/mwgui/windowmanagerimp.cpp','        if (!mCurrentModals.empty())\n            mCurrentModals.back()->onFrame(frameDuration);',
'''        for (std::size_t i = 0; i < mCurrentModals.size(); ++i)
            mCurrentModals[i]->mMainWidget->setUserString("AstraModalTop", i + 1 == mCurrentModals.size() ? "true" : "false");
        if (!mCurrentModals.empty())
            mCurrentModals.back()->onFrame(frameDuration);''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraUiEdit"]',
'''        api["_astraUiAdjust"] = [context](const std::string& ref, std::size_t position) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()) return false;
            return AstraUI::adjust(MWBase::Environment::get().getWindowManager(), ref, position);
        };
        api["_astraUiEdit"]''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraUiEdit"]',
'''        api["_astraProjectileParameters"] = [context](sol::this_state state) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning())
                throw std::runtime_error("Astra projectile parameters require player onFrame");
            return AstraCombat::projectileParameters(state);
        };
        api["_astraUiEdit"]''')
for stat in ('Skill','Attribute'):
    anchor=f'''                m{stat}ValueWidget->_setWidgetState("normal");
        }}
    }}

    void MW{stat}::setStateSelected'''
    added=f'''                m{stat}ValueWidget->_setWidgetState("normal");
        }}
        setUserString("AstraStatName", m{stat}NameWidget ? m{stat}NameWidget->getCaption().asUTF8() : "");
        setUserString("AstraStatValue", m{stat}ValueWidget ? m{stat}ValueWidget->getCaption().asUTF8() : "");
        setUserString("AstraStatInteractive", m{stat}NameWidget && m{stat}NameWidget->isType<MyGUI::Button>() ? "true" : "false");
    }}

    void MW{stat}::setStateSelected'''
    replace('apps/openmw/mwgui/widgets.cpp',anchor,added)
replace('apps/openmw/mwgui/widgets.cpp',
'''                mSpellNameWidget->setCaption({});
        }
    }''',
'''                mSpellNameWidget->setCaption({});
        }
        setUserString("AstraSpellName", mSpellNameWidget ? mSpellNameWidget->getCaption().asUTF8() : "");
    }''')
replace('apps/openmw/mwgui/bookpage.hpp',
    'astraVisibleRuns() const', 'astraVisibleRuns(bool visibleOnly = true) const')
replace('apps/openmw/mwgui/bookpage.cpp',
    'astraVisibleRuns() const', 'astraVisibleRuns(bool visibleOnly) const')
replace('apps/openmw/mwgui/bookpage.cpp',
    'if (line.mRect.bottom <= mPageDisplay->mViewTop || line.mRect.top >= mPageDisplay->mViewBottom) continue;',
    'if (visibleOnly && (line.mRect.bottom <= mPageDisplay->mViewTop || line.mRect.top >= mPageDisplay->mViewBottom)) continue;')
replace('apps/openmw/mwbase/inputmanager.hpp',
    '        virtual void warpMouseToWidget(MyGUI::Widget* widget) = 0;',
'''        virtual void warpMouseToWidget(MyGUI::Widget* widget) = 0;
        virtual void injectUiMouseMove(int x, int y) = 0;''')
replace('apps/openmw/mwinput/inputmanagerimp.hpp',
    '        void warpMouseToWidget(MyGUI::Widget* widget) override;',
'''        void warpMouseToWidget(MyGUI::Widget* widget) override;
        void injectUiMouseMove(int x, int y) override;''')
replace('apps/openmw/mwinput/inputmanagerimp.cpp',
    '    void InputManager::warpMouseToWidget(MyGUI::Widget* widget)',
'''    void InputManager::injectUiMouseMove(int x, int y)
    {
        mMouseManager->injectUiMouseMove(x, y);
    }

    void InputManager::warpMouseToWidget(MyGUI::Widget* widget)''')
replace('apps/openmw/mwinput/mousemanager.hpp',
    '        void injectMouseMove(float xMove, float yMove, float mouseWheelMove);',
'''        void injectMouseMove(float xMove, float yMove, float mouseWheelMove);
        void injectUiMouseMove(int x, int y) { injectMouseMove(x - mGuiCursorX, y - mGuiCursorY, 0); }''')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraUiEdit"]',
'''        api["_astraUiHover"] = [context, windowManager](const std::string& ref) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()) return false;
            return AstraUI::hover(windowManager, ref);
        };
        api["_astraUiScroll"] = [context, windowManager](int steps) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()) return false;
            return AstraUI::scroll(windowManager, steps);
        };
        api["_astraUiEdit"]''')
print('Astra patch applied (dialogue accessibility and native UI pointer).')
# A render-completion capture hook is required for paced, tear-free video.
frame_source=Path(__file__).with_name('astraframe.hpp')
frame_target=root/'components/sdlutil/astraframe.hpp'
if not frame_target.exists() or frame_target.read_bytes()!=frame_source.read_bytes():
    shutil.copyfile(frame_source,frame_target)
replace('components/sdlutil/sdlgraphicswindow.cpp', '#include "sdlgraphicswindow.hpp"',
        '#include "sdlgraphicswindow.hpp"\n#include "astraframe.hpp"')
replace('components/sdlutil/sdlgraphicswindow.cpp', '        SDL_GL_SwapWindow(mWindow);',
        '        AstraFrame::capture(mWindow);\n        SDL_GL_SwapWindow(mWindow);')
