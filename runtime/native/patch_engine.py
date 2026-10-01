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
# Stable roles on existing, displayed controls. Values are the same visible
# prices/amounts the ordinary callbacks act on; no service bypass is exposed.
for filename, fields in {
    'waitdialog.cpp': {'mHourSlider':('HourSlider','rest_hours'), 'mWaitButton':('WaitButton','rest_confirm'),
                       'mCancelButton':('CancelButton','rest_cancel')},
    'countdialog.cpp': {'mSlider':('CountSlider','quantity_slider'), 'mItemEdit':('ItemEdit','quantity_value'),
                        'mOkButton':('OkButton','quantity_confirm'), 'mCancelButton':('CancelButton','quantity_cancel')},
    'tradewindow.cpp': {'mOfferButton':('OfferButton','trade_offer'), 'mCancelButton':('CancelButton','trade_cancel'),
                        'mTotalBalance':('TotalBalance','trade_balance')},
}.items():
    for member, (widget, role) in fields.items():
        line=f'        getWidget({member}, "{widget}");'
        replace('apps/openmw/mwgui/'+filename,line,line+f'\n        {member}->setUserString("AstraControl", "{role}");')
replace('apps/openmw/mwgui/tradewindow.cpp','    void TradeWindow::updateLabels()\n    {',
'''    void TradeWindow::updateLabels()
    {
        mTotalBalance->setUserString("AstraValue", std::to_string(mCurrentBalance));''')
replace('apps/openmw/mwgui/travelwindow.cpp','        toAdd->setUserString("price", std::to_string(price));',
'''        toAdd->setUserString("price", std::to_string(price));
        toAdd->setUserString("AstraControl", "travel_destination");''')
replace('apps/openmw/mwgui/travelwindow.cpp','#include "travelwindow.hpp"',
        '#include "travelwindow.hpp"\n#include <MyGUI_LanguageManager.h>')
replace('apps/openmw/mwgui/travelwindow.cpp','        toAdd->setUserString("AstraControl", "travel_destination");',
'''        toAdd->setUserString("AstraControl", "travel_destination");
        toAdd->setUserString("AstraDestination",
            MyGUI::LanguageManager::getInstance().replaceTags("#{sCell=" + nameString + "}").asUTF8());''')
# Carry semantics from the service's construction to the rendered list item.
# Labels remain localized; neither the adapter nor the harness parses them.
notice_codes={'sMagicSkillFail':'spell_failed','sLockSuccess':'lock_opened','sLockFail':'lock_failed',
    'sLockImpossible':'lock_impossible','sTrapSuccess':'trap_disarmed','sTrapFail':'trap_failed',
    'sNotifyMessage45':'missing_mortar','sNotifyMessage37':'potion_name_required',
    'sNotifyMessage6a':'ingredients_required','sNotifyMessage8':'potion_failed','sPotionSuccess':'potion_created'}
notice_lines='\n'.join(f'        if (mMessage.starts_with("#{{{setting}}}")) mMessageWidget->setUserString("AstraNotice", "{code}");'
                       for setting,code in notice_codes.items())
replace('apps/openmw/mwgui/messagebox.cpp','        mMessageWidget->setCaptionWithReplacing(mMessage);',
        '        mMessageWidget->setCaptionWithReplacing(mMessage);\n'+notice_lines)
replace('components/widgets/list.hpp','void addItem(std::string_view name, int verticalPadding = 0);',
        'void addItem(std::string_view name, int verticalPadding = 0, std::string_view astraControl = {});')
replace('components/widgets/list.hpp','            std::string mName;',
        '            std::string mName;\n            std::string mAstraControl;')
replace('components/widgets/list.hpp','ListItemData(std::string_view name, int verticalPadding)\n                : mName(name)',
        'ListItemData(std::string_view name, int verticalPadding, std::string_view astraControl)\n                : mName(name)\n                , mAstraControl(astraControl)')
replace('components/widgets/list.cpp','void MWList::addItem(std::string_view name, int verticalPadding)\n    {\n        mItems.emplace_back(name, verticalPadding);',
        'void MWList::addItem(std::string_view name, int verticalPadding, std::string_view astraControl)\n    {\n        mItems.emplace_back(name, verticalPadding, astraControl);')
replace('components/widgets/list.cpp','                button->setCaption(item.mName);',
        '                button->setCaption(item.mName);\n                button->setUserString("AstraControl", item.mAstraControl);')
for setting, control in {'sPersuasion':'service_persuasion','sBarter':'service_barter',
        'sSpells':'service_spells','sTravel':'service_travel','sSpellmakingMenuTitle':'service_spellmaking',
        'sEnchanting':'service_enchanting','sServiceTrainingTitle':'service_training',
        'sRepair':'service_repair','sCompanionShare':'service_companion'}.items():
    replace('apps/openmw/mwgui/dialogue.cpp',f'mTopicsList->addItem(gmst.find("{setting}")->mValue.getString());',
            f'mTopicsList->addItem(gmst.find("{setting}")->mValue.getString(), 0, "{control}");')
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
replace('apps/openmw/mwlua/uibindings.cpp',
'''        api["_astraActivate"] = [context, windowManager]() {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()
                || windowManager->isGuiMode()) return false;
            MWBase::Environment::get().getInputManager()->executeAction(MWInput::A_Activate);
            return true;
        };''',
'''        api["_astraIsActivationTarget"] = [context, windowManager](const LObject& expected) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()
                || windowManager->isGuiMode()) return false;
            return MWBase::Environment::get().getWorld()->getFocusObject() == expected.ptr();
        };
        api["_astraActivate"] = [context, windowManager](sol::optional<LObject> expected) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning()
                || windowManager->isGuiMode()) return false;
            // Check the exact ray used by ordinary Activate, after the camera
            // has reached a rendered frame. Never substitute a nearby object.
            if (expected && MWBase::Environment::get().getWorld()->getFocusObject() != expected->ptr()) return false;
            MWBase::Environment::get().getInputManager()->executeAction(MWInput::A_Activate);
            return true;
        };''')
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
frame_hook = '        const auto* stamp=getState()->getFrameStamp();\n        AstraFrame::capture(mWindow,stamp ? stamp->getFrameNumber() : 0);'
if '        AstraFrame::capture(mWindow);' in (root/'components/sdlutil/sdlgraphicswindow.cpp').read_text():
    replace('components/sdlutil/sdlgraphicswindow.cpp','        AstraFrame::capture(mWindow);',frame_hook)
replace('components/sdlutil/sdlgraphicswindow.cpp', '        SDL_GL_SwapWindow(mWindow);',
        frame_hook+'\n        SDL_GL_SwapWindow(mWindow);')

replace('apps/openmw/mwlua/uibindings.cpp',
    'api["_astraUiSnapshot"] = [context, windowManager](sol::this_state state) {',
    'api["_astraUiSnapshot"] = [context, windowManager](sol::this_state state, const std::string& epoch) {\n            AstraUI::beginEpoch(epoch);')
replace('apps/openmw/mwlua/uibindings.cpp','        api["_astraDoorDescription"]',
'''        api["_astraOwnedItemInfo"] = [context](sol::this_state state, const LObject& object, const std::string& epoch) {
            if (context.mType != Context::Local || !context.mLuaManager->isSynchronizedUpdateRunning())
                throw std::runtime_error("Astra inventory requires player onFrame");
            AstraUI::beginEpoch(epoch);
            return AstraUI::ownedItemInfo(state,object);
        };
        api["_astraDoorDescription"]''')

# Engine-owned audiovisual timeline and synchronous OpenAL loopback mixing.
media_source=Path(__file__).with_name('astramedia.hpp')
media_target=root/'components/sdlutil/astramedia.hpp'
if not media_target.exists() or media_target.read_bytes()!=media_source.read_bytes():
    shutil.copyfile(media_source,media_target)
replace('apps/openmw/engine.cpp', '#include "engine.hpp"', '#include "engine.hpp"\n#include <components/sdlutil/astramedia.hpp>')
replace('apps/openmw/engine.cpp', '            if (mUseSound)\n                mSoundManager->update(frametime);',
        '            if (mUseSound && !AstraMedia::stream().enabled())\n                mSoundManager->update(frametime);')
replace('apps/openmw/engine.cpp', '        bool paused = mWorld->getTimeManager()->isPaused();',
'''        bool paused = mWorld->getTimeManager()->isPaused();
        AstraMedia::stream().begin(frametime, !paused
            && mStateManager->getState() != MWBase::StateManager::State_NoGame);''')
if '            AstraMedia::stream().render();' in (root/'apps/openmw/engine.cpp').read_text():
    replace('apps/openmw/engine.cpp','            AstraMedia::stream().render();',
        '            AstraMedia::stream().render(mViewer->getFrameStamp()->getFrameNumber());')
replace('apps/openmw/engine.cpp', '            mWindowManager->update(frametime);\n        }',
'''            mWindowManager->update(frametime);
        }
        if (AstraMedia::stream().enabled())
        {
            if (mUseSound && AstraMedia::stream().active) mSoundManager->update(frametime);
            AstraMedia::stream().render(mViewer->getFrameStamp()->getFrameNumber());
        }''')
replace('apps/openmw/mwsound/openaloutput.hpp', '        ALCcontext* mContext;',
'''        ALCcontext* mContext;
        bool mAstraLoopback = false;
        unsigned mAstraMonitor = 0;
        void astraMix(float* samples, unsigned count);''')
replace('apps/openmw/mwsound/openaloutput.cpp', '#include "soundmanagerimp.hpp"',
'''#include "soundmanagerimp.hpp"
#include <components/sdlutil/astramedia.hpp>
#include <SDL_audio.h>
#include <SDL.h>''')
replace('apps/openmw/mwsound/openaloutput.cpp', '        mDevice = alcOpenDevice(devname.c_str());',
'''        mAstraLoopback = AstraMedia::stream().enabled();
        if (mAstraLoopback)
        {
            LPALCLOOPBACKOPENDEVICESOFT openLoopback = nullptr;
            getALCFunc(openLoopback, nullptr, "alcLoopbackOpenDeviceSOFT");
            if (!openLoopback) return false;
            mDevice = openLoopback(nullptr);
            if (!mDevice) return false;
        }
        else mDevice = alcOpenDevice(devname.c_str());''')
replace('apps/openmw/mwsound/openaloutput.cpp', '        mContextAttributes.reserve(15);',
'''        mContextAttributes.reserve(23);
        if (mAstraLoopback)
            mContextAttributes.insert(mContextAttributes.end(), {
                ALC_FORMAT_CHANNELS_SOFT, ALC_STEREO_SOFT,
                ALC_FORMAT_TYPE_SOFT, ALC_FLOAT_SOFT, ALC_FREQUENCY, 48000});''')
replace('apps/openmw/mwsound/openaloutput.cpp', '        if (alcIsExtensionPresent(mDevice, "ALC_SOFT_reopen_device"))',
        '        if (!mAstraLoopback && alcIsExtensionPresent(mDevice, "ALC_SOFT_reopen_device"))')
replace('apps/openmw/mwsound/openaloutput.cpp', '        if (mDeviceName.empty() && !name.empty())',
        '        if (!mAstraLoopback && mDeviceName.empty() && !name.empty())')
replace('apps/openmw/mwsound/openaloutput.cpp', '        mInitialized = true;\n        return true;',
'''        if (mAstraLoopback)
        {
            SDL_AudioSpec spec{};
            spec.freq=48000; spec.format=AUDIO_F32SYS; spec.channels=2; spec.samples=1024;
            if (SDL_InitSubSystem(SDL_INIT_AUDIO)==0)
                mAstraMonitor=SDL_OpenAudioDevice(nullptr,0,&spec,nullptr,0);
            if (mAstraMonitor) SDL_PauseAudioDevice(mAstraMonitor,0);
            else Log(Debug::Warning) << "Astra audio monitoring unavailable: " << SDL_GetError();
            AstraMedia::stream().monitor(mAstraMonitor!=0);
            AstraMedia::stream().mixer([this](float* pcm,unsigned count) { astraMix(pcm,count); });
        }
        mInitialized = true;
        return true;''')
replace('apps/openmw/mwsound/openaloutput.cpp', '    void OpenALOutput::deinit()\n    {',
'''    void OpenALOutput::astraMix(float* samples, unsigned count)
    {
        LPALCRENDERSAMPLESSOFT render = nullptr;
        getALCFunc(render,mDevice,"alcRenderSamplesSOFT");
        // Refill streams before every mix, including the first frame of a voice.
        // The background refill thread may sleep for 50 ms; it must not control
        // progress on the sample clock or cause loopback underruns.
        std::lock_guard<std::mutex> lock(mStreamThread->mMutex);
        for (auto* stream : mStreamThread->mStreams) stream->process();
        render(mDevice,samples,count);
        if (mAstraMonitor)
        {
            bool overflow=SDL_GetQueuedAudioSize(mAstraMonitor)>48000*8/4;
            if (overflow) SDL_ClearQueuedAudio(mAstraMonitor);
            AstraMedia::stream().monitor(true,overflow);
            SDL_QueueAudio(mAstraMonitor,samples,count*8);
        }
    }

    void OpenALOutput::deinit()
    {
        if (mAstraLoopback) AstraMedia::stream().mixer({});
        if (mAstraMonitor) SDL_CloseAudioDevice(mAstraMonitor);
        mAstraMonitor=0;
        mAstraLoopback=false;''')
for method in ('pauseActiveDevice','resumeActiveDevice'):
    replace('apps/openmw/mwsound/openaloutput.cpp', f'    void OpenALOutput::{method}()\n    {{',
            f'    void OpenALOutput::{method}()\n    {{\n        if (mAstraLoopback) return;')

# Production input policy: disable execution as well as the console window.
replace('apps/openmw/options.cpp',
        '        addOption("script-console",',
        '        addOption("disable-console", bpo::bool_switch(), "disable console UI and command execution");\n\n        addOption("script-console",')
replace('apps/openmw/main.cpp',
        '    engine.setScriptConsoleMode(variables["script-console"].as<bool>());',
'''    const bool disableConsole = variables["disable-console"].as<bool>();
    if (disableConsole && !variables["script-run"].as<std::string>().empty())
        throw std::runtime_error("--disable-console cannot be combined with --script-run");
    engine.setConsoleDisabled(disableConsole);
    engine.setScriptConsoleMode(variables["script-console"].as<bool>());''')
replace('apps/openmw/engine.hpp', '        bool mScriptConsoleMode;',
        '        bool mScriptConsoleMode;\n        bool mConsoleDisabled = false;')
replace('apps/openmw/engine.hpp', '        void setScriptConsoleMode(bool enabled);',
        '        void setScriptConsoleMode(bool enabled);\n        void setConsoleDisabled(bool disabled) { mConsoleDisabled = disabled; }')
replace('apps/openmw/engine.cpp',
        'mCfgMgr.getLogPath(), mScriptConsoleMode, mTranslationDataStorage',
        'mCfgMgr.getLogPath(), mScriptConsoleMode, mConsoleDisabled, mTranslationDataStorage')
replace('apps/openmw/mwbase/windowmanager.hpp',
        '        virtual void executeInConsole(const std::filesystem::path& path) = 0;',
        '        virtual void executeInConsole(const std::filesystem::path& path) = 0;\n        virtual bool isConsoleDisabled() const { return false; }')
replace('apps/openmw/mwgui/windowmanagerimp.hpp',
        'const std::filesystem::path& logpath, bool consoleOnlyScripts, Translation::Storage& translationDataStorage,',
        'const std::filesystem::path& logpath, bool consoleOnlyScripts, bool consoleDisabled, Translation::Storage& translationDataStorage,')
replace('apps/openmw/mwgui/windowmanagerimp.hpp', '        bool mConsoleOnlyScripts;',
        '        bool mConsoleOnlyScripts;\n        const bool mConsoleDisabled;')
replace('apps/openmw/mwgui/windowmanagerimp.hpp', '        void toggleConsole() override;',
        '        void toggleConsole() override;\n        bool isConsoleDisabled() const override { return mConsoleDisabled; }')
replace('apps/openmw/mwgui/windowmanagerimp.cpp',
        'bool consoleOnlyScripts, Translation::Storage& translationDataStorage, ToUTF8::FromType encoding,',
        'bool consoleOnlyScripts, bool consoleDisabled, Translation::Storage& translationDataStorage, ToUTF8::FromType encoding,')
replace('apps/openmw/mwgui/windowmanagerimp.cpp', '        , mConsoleOnlyScripts(consoleOnlyScripts)',
        '        , mConsoleOnlyScripts(consoleOnlyScripts)\n        , mConsoleDisabled(consoleDisabled)')
replace('apps/openmw/mwgui/windowmanagerimp.cpp',
        'std::make_unique<Console>(w, h, mConsoleOnlyScripts, mCfgMgr)',
        'std::make_unique<Console>(w, h, mConsoleOnlyScripts, mConsoleDisabled, mCfgMgr)')
replace('apps/openmw/mwgui/windowmanagerimp.cpp', '    void WindowManager::toggleConsole()\n    {',
        '    void WindowManager::toggleConsole()\n    {\n        if (mConsoleDisabled) return;')
replace('apps/openmw/mwgui/console.hpp',
        'Console(int w, int h, bool consoleOnlyScripts, Files::ConfigurationManager& cfgMgr);',
        'Console(int w, int h, bool consoleOnlyScripts, bool disabled, Files::ConfigurationManager& cfgMgr);')
replace('apps/openmw/mwgui/console.hpp', '        bool mConsoleOnlyScripts;',
        '        bool mConsoleOnlyScripts;\n        const bool mDisabled;')
replace('apps/openmw/mwgui/console.cpp',
        'Console::Console(int w, int h, bool consoleOnlyScripts, Files::ConfigurationManager& cfgMgr)',
        'Console::Console(int w, int h, bool consoleOnlyScripts, bool disabled, Files::ConfigurationManager& cfgMgr)')
replace('apps/openmw/mwgui/console.cpp', '        , mConsoleOnlyScripts(consoleOnlyScripts)',
        '        , mConsoleOnlyScripts(consoleOnlyScripts)\n        , mDisabled(disabled)')
for signature in ('execute(const std::string& command)', 'executeFile(const std::filesystem::path& path)', 'onOpen()'):
    replace('apps/openmw/mwgui/console.cpp', f'    void Console::{signature}\n    {{',
            f'    void Console::{signature}\n    {{\n        if (mDisabled) return;')
replace('apps/openmw/mwlua/luamanagerimp.cpp',
'''        const std::string& consoleMode, const std::string& command, const MWWorld::Ptr& selectedPtr)
    {''',
'''        const std::string& consoleMode, const std::string& command, const MWWorld::Ptr& selectedPtr)
    {
        if (MWBase::Environment::get().getWindowManager()->isConsoleDisabled()) return;''')
