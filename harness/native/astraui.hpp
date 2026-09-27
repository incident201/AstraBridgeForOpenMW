// Optional OpenMW 0.51 UI accessibility adapter. No world/database reads.
#pragma once
#include <MyGUI_Gui.h>
#include <MyGUI_InputManager.h>
#include <MyGUI_RenderManager.h>
#include <MyGUI_TextBox.h>
#include <MyGUI_Button.h>
#include <MyGUI_EditBox.h>
#include <MyGUI_TextIterator.h>
#include <MyGUI_ProgressBar.h>
#include <MyGUI_LanguageManager.h>
#include <MyGUI_ILayer.h>
#include <MyGUI_ScrollView.h>
#include <MyGUI_ScrollBar.h>
#include <MyGUI_ListBox.h>
#include <components/widgets/imagebutton.hpp>
#include <components/widgets/list.hpp>
#include <components/esm3/loaddoor.hpp>
#include <components/esm3/loadcont.hpp>
#include "../mwgui/bookpage.hpp"
#include "../mwgui/itemwidget.hpp"
#include "../mwgui/itemview.hpp"
#include "../mwgui/itemchargeview.hpp"
#include "../mwgui/itemmodel.hpp"
#include "../mwgui/inventorywindow.hpp"
#include "../mwgui/tradewindow.hpp"
#include "../mwgui/tooltips.hpp"
#include "../mwgui/widgets.hpp"
#include "../mwgui/windowbase.hpp"
#include "../mwbase/inputmanager.hpp"
#include "../mwworld/class.hpp"
#include "../mwworld/cellref.hpp"
#include "../mwworld/inventorystore.hpp"
#include "../mwbase/world.hpp"
#include "../mwbase/mechanicsmanager.hpp"
#include "object.hpp"
#include <algorithm>
#include <functional>
#include <sstream>
#include <map>
#include <components/esm3/loadrepa.hpp>
#include "astracombat.hpp"
#include "../mwmechanics/magiceffects.hpp"

namespace MWLua::AstraUI
{
    inline std::map<MWWorld::Ptr, std::uint64_t> itemInstances;
    inline std::uint64_t itemSerial = 0;
    inline std::string itemEpoch;
    inline void beginEpoch(const std::string& epoch)
    {
        if (epoch!=itemEpoch) { itemInstances.clear(); itemEpoch=epoch; }
    }
    inline std::string itemIdentity(const MWWorld::Ptr& ptr)
    {
        auto [it, inserted]=itemInstances.try_emplace(ptr,0);
        if (inserted) it->second=++itemSerial;
        return std::to_string(it->second);
    }
    struct Entry
    {
        std::string text, role;
        MyGUI::IntRect rect;
        bool enabled = false;
        std::function<void()> action;
        std::string panel, description, unavailableReason, instance;
        int count = 0;
        int conditionCurrent = -1, conditionMax = -1;
        bool equipped = false, pendingTrade = false;
        bool selected = false;
        bool screenVisible = true;
        std::function<void(const std::string&)> edit;
        std::function<void(std::size_t)> adjust;
        std::size_t sliderPosition = 0, sliderMax = 0;
        Entry(std::string label,std::string type,MyGUI::IntRect bounds,bool available,std::function<void()> callback)
            : text(std::move(label)),role(std::move(type)),rect(bounds),enabled(available),action(std::move(callback)) {}
    };
    struct Snapshot
    {
        std::vector<Entry> entries;
        bool modal = false;
        std::string revision;
        std::string dialogueText;
        bool dialogue = false;
        std::string documentText, documentTitle, documentKind, documentRef;
    };
    inline MyGUI::IntRect intersection(MyGUI::IntRect a, MyGUI::IntRect b)
    {
        return {std::max(a.left,b.left),std::max(a.top,b.top),std::min(a.right,b.right),std::min(a.bottom,b.bottom)};
    }
    inline bool empty(MyGUI::IntRect r) { return r.right <= r.left || r.bottom <= r.top; }
    inline MyGUI::Widget* root(MyGUI::Widget* w)
    {
        while (w && w->getParent()) w=w->getParent();
        return w;
    }
    inline std::string plain(const MyGUI::UString& text)
    {
        return MyGUI::TextIterator::getOnlyText(text).asUTF8();
    }
    inline std::string fingerprint(const std::string& text)
    {
        std::uint64_t hash=1469598103934665603ull;
        for (unsigned char c:text) { hash^=c; hash*=1099511628211ull; }
        std::ostringstream value; value<<std::hex<<hash; return value.str();
    }
    inline void documentText(MyGUI::Widget* w, std::string& text)
    {
        // Formatter-created captions of the OPEN document, in layout order.
        // Clipping/pagination does not change their content. Never read book records.
        if (auto* box=w->castType<MyGUI::TextBox>(false))
        {
            auto caption=plain(box->getCaption());
            if (!caption.empty())
            {
                if (!text.empty() && text.back()!='\n' && caption.front()!='\n') text+='\n';
                text+=caption;
            }
            return;
        }
        auto children=w->getEnumerator();
        while (children.next()) documentText(children.current(),text);
    }
    inline bool inDialogue(MyGUI::Widget* w, MWBase::WindowManager* wm)
    {
        if (!wm->containsMode(MWGui::GM_Dialogue)) return false;
        for (auto* window : wm->getGuiModeWindows(MWGui::GM_Dialogue))
            if (window && root(w)==root(window->mMainWidget)) return true;
        return false;
    }
    inline void visit(MyGUI::Widget* w, MyGUI::IntRect clip, MyGUI::Widget* modalRoot,
        MWBase::WindowManager* wm, Snapshot& out, int depth=0)
    {
        if (!w || depth>30 || !w->getInheritedVisible() || w->getAlpha()<=0) return;
        const std::string document(w->getUserString("AstraDocumentBody"));
        if (!document.empty())
        {
            // The right page contains a second copy of the same formatted book.
            if (document!="duplicate")
            {
                out.documentKind=document;
                out.documentTitle=w->getUserString("AstraDocumentTitle");
                documentText(w,out.documentText);
                out.documentRef="document_"+fingerprint(document+"\n"+out.documentTitle+"\n"
                    +std::string(w->getUserString("AstraDocumentInstance"))+"\n"+out.documentText);
            }
            return; // Full text is delivered only by bounded read(), never duplicated in observations.
        }
        clip=intersection(clip,w->getAbsoluteRect());
        if (empty(clip)) return;
        const bool enabled=w->getInheritedEnabled() && (!out.modal || root(w)==modalRoot)
            && w->getUserString("AstraUnavailableReason").empty();
        if (auto* list=w->castType<Gui::MWList>(false))
        {
            // The current dialogue's already populated sidebar, including services.
            // No dialogue database or response lookup: scrolling is presentation only.
            for (std::size_t i=0;i<list->getItemCount();++i)
            {
                const auto& name=list->getItemNameAt(i);
                if (name.empty()) continue; // separator
                auto* item=list->getItemWidget(name);
                if (!item || !item->getInheritedVisible()) continue;
                const auto rect=intersection(clip,item->getAbsoluteRect());
                Entry e{plain(item->getCaption()),"button",rect,
                    enabled && item->getInheritedEnabled(),[item]{item->eventMouseButtonClick(item);}};
                e.panel=inDialogue(w,wm)?"dialogue_topics":"list";
                e.screenVisible=!empty(rect);
                out.entries.push_back(std::move(e));
            }
            return;
        }
        if (w->isType<MWGui::Widgets::MWSkill>() || w->isType<MWGui::Widgets::MWAttribute>())
        {
            const auto name=plain(MyGUI::UString(w->getUserString("AstraStatName")));
            const auto value=plain(MyGUI::UString(w->getUserString("AstraStatValue")));
            const bool interactive=w->getUserString("AstraStatInteractive")=="true";
            if (!name.empty())
            {
                Entry e{name+(value.empty()?"":": "+value),interactive?"button":"text",clip,enabled && interactive,{}};
                if (interactive) e.action=[w] {
                    if (auto* skill=w->castType<MWGui::Widgets::MWSkill>(false)) skill->eventClicked(skill);
                    else if (auto* attribute=w->castType<MWGui::Widgets::MWAttribute>(false)) attribute->eventClicked(attribute);
                };
                for (int i=0;i<5;++i)
                {
                    if (w->getName().ends_with("MajorSkill"+std::to_string(i))) e.panel="major_skills";
                    if (w->getName().ends_with("MinorSkill"+std::to_string(i))) e.panel="minor_skills";
                }
                if (w->getName().ends_with("FavoriteAttribute0") || w->getName().ends_with("FavoriteAttribute1")) e.panel="favored_attributes";
                out.entries.push_back(std::move(e));
            }
            return;
        }
        if (auto* list=w->castType<MyGUI::ListBox>(false))
        {
            // All rows populated in this OPEN list. Scrolling changes only presentation.
            for (std::size_t i=0;i<list->getItemCount();++i)
            {
                MyGUI::IntRect rect{};
                if (list->isItemVisibleAt(i))
                    if (auto* item=list->getWidgetByIndex(i)) rect=intersection(clip,item->getAbsoluteRect());
                Entry e{plain(list->getItemNameAt(i)),"list_item",rect,enabled,[list,i] {
                    list->setIndexSelected(i);
                    list->eventListChangePosition(list,i);
                    list->eventListMouseItemActivate(list,i);
                }};
                e.selected=list->getIndexSelected()==i;
                e.screenVisible=!empty(rect);
                out.entries.push_back(std::move(e));
            }
            return;
        }
        if (auto* view=w->castType<MWGui::ItemChargeView>(false))
        {
            // These rows live in MyGUI skin children. Use the current UI rows,
            // including scrolled-out ones, and their normal click delegates.
            for (auto* icon:view->astraItemWidgets())
            {
                auto* ptr=icon->getUserData<MWWorld::Ptr>(false);
                if (!ptr || ptr->isEmpty()) continue;
                const auto& cls=ptr->getClass();
                auto rect=intersection(clip,icon->getAbsoluteRect());
                Entry e{std::string(cls.getName(*ptr)),"item",rect,
                    enabled && icon->getInheritedEnabled(),[icon]{icon->eventMouseButtonClick(icon);}};
                e.panel=wm->containsMode(MWGui::GM_Repair)?"repair":"recharge";
                e.count=ptr->getCellRef().getCount();
                e.instance=itemIdentity(*ptr);
                const auto player=MWBase::Environment::get().getWorld()->getPlayerPtr();
                e.equipped=player.getClass().getInventoryStore(player).isEquipped(*ptr);
                e.description=plain(MyGUI::LanguageManager::getInstance().replaceTags(cls.getToolTipInfo(*ptr,e.count).text));
                if (cls.hasItemHealth(*ptr))
                { e.conditionCurrent=cls.getItemHealth(*ptr); e.conditionMax=cls.getItemMaxHealth(*ptr); }
                e.screenVisible=!empty(rect);
                out.entries.push_back(std::move(e));
            }
            return;
        }
        if (auto* view=w->castType<MWGui::ItemView>(false))
        {
            std::string panel;
            if (root(w)==root(wm->getInventoryWindow()->mMainWidget)) panel="inventory";
            else if (root(w)==root(wm->getTradeWindow()->mMainWidget)) panel="merchant";
            else if (wm->containsMode(MWGui::GM_Alchemy)) panel="alchemy";
            else if (wm->containsMode(MWGui::GM_Enchanting)) panel="enchanting";
            else panel="container";
            if (panel!="alchemy" && panel!="enchanting")
            {
                Entry area{panel+" area","drop_target",clip,enabled,[view]{view->eventBackgroundClicked();}};
                area.panel=panel;
                out.entries.push_back(std::move(area));
            }
            // The model belongs to this currently opened and filtered item view.
            // Its normal event delegate performs the same trade/use action as a click.
            auto* model=view->getModel();
            if (model) for (std::size_t i=0;i<model->getItemCount();++i)
            {
                const auto item=model->getItem(static_cast<MWGui::ItemModel::ModelIndex>(i));
                if (item.mBase.isEmpty()) continue;
                const auto& cls=item.mBase.getClass();
                Entry e{std::string(cls.getName(item.mBase)),"item",{},enabled,[view,i]{
                    view->eventItemClicked(static_cast<MWGui::ItemModel::ModelIndex>(i));
                }};
                e.panel=panel;e.count=static_cast<int>(item.mCount);
                e.instance=itemIdentity(item.mBase);
                e.equipped=item.mType==MWGui::ItemStack::Type_Equipped;
                e.pendingTrade=item.mType==MWGui::ItemStack::Type_Barter;
                e.description=plain(MyGUI::LanguageManager::getInstance().replaceTags(cls.getToolTipInfo(item.mBase,e.count).text));
                if (cls.hasItemHealth(item.mBase))
                { e.conditionCurrent=cls.getItemHealth(item.mBase);e.conditionMax=cls.getItemMaxHealth(item.mBase); }
                e.screenVisible=false;
                auto* scroll=view->astraScrollView();
                if (scroll && scroll->getChildCount())
                {
                    auto* area=scroll->getChildAt(0);
                    for (std::size_t j=0;j<area->getChildCount();++j)
                    {
                        auto* icon=area->getChildAt(j);
                        auto* data=icon->getUserData<std::pair<MWGui::ItemModel::ModelIndex,MWGui::ItemModel*>>(false);
                        if (data && data->second==model && data->first==static_cast<MWGui::ItemModel::ModelIndex>(i))
                        { e.rect=intersection(clip,icon->getAbsoluteRect());e.screenVisible=!empty(e.rect);break; }
                    }
                }
                out.entries.push_back(std::move(e));
            }
            return;
        }
        if (w->isType<MWGui::ItemWidget>() && w->getUserString("ToolTipType")=="ItemModelIndex")
        {
            // This is the displayed (filtered/trade/container) model, not an actor's raw inventory.
            auto* data=w->getUserData<std::pair<MWGui::ItemModel::ModelIndex,MWGui::ItemModel*>>(false);
            if (data && data->second && data->first>=0 && static_cast<std::size_t>(data->first)<data->second->getItemCount())
            {
                const auto item=data->second->getItem(data->first);
                if (!item.mBase.isEmpty())
                {
                    const auto& cls=item.mBase.getClass();
                    Entry e{std::string(cls.getName(item.mBase)),"item",clip,enabled,[w]{w->eventMouseButtonClick(w);}};
                    e.count=static_cast<int>(item.mCount);
                    e.equipped=item.mType==MWGui::ItemStack::Type_Equipped;
                    e.pendingTrade=item.mType==MWGui::ItemStack::Type_Barter;
                    auto info=cls.getToolTipInfo(item.mBase,e.count);
                    // Do not expose raw enchantment IDs, ingredient effect records or debug extra text.
                    e.description=plain(MyGUI::LanguageManager::getInstance().replaceTags(info.text));
                    if (root(w)==root(wm->getInventoryWindow()->mMainWidget)) e.panel="inventory";
                    else if (root(w)==root(wm->getTradeWindow()->mMainWidget)) e.panel="merchant";
                    else if (wm->containsMode(MWGui::GM_Alchemy)) e.panel="alchemy";
                    else if (wm->containsMode(MWGui::GM_Enchanting)) e.panel="enchanting";
                    else e.panel="container";
                    out.entries.push_back(std::move(e));
                }
            }
            return; // the icon's child count text would duplicate this entry
        }
        if (w->isType<MWGui::ItemWidget>())
        {
            std::string label,panel;
            const auto& name=w->getName();
            bool apparatus=false;
            if (wm->containsMode(MWGui::GM_Alchemy))
            {
                for (int i=1;i<=4;++i)
                {
                    if (name.ends_with("Ingredient"+std::to_string(i))) label="ingredient "+std::to_string(i);
                    if (name.ends_with("Apparatus"+std::to_string(i)))
                    {label="apparatus "+std::to_string(i);apparatus=true;}
                }
                panel="alchemy";
            }
            else if (wm->containsMode(MWGui::GM_Enchanting))
            {
                if (name.ends_with("ItemBox")) label="enchant item";
                if (name.ends_with("SoulBox")) label="soul gem";
                panel="enchanting";
            }
            else if (wm->containsMode(MWGui::GM_Repair) && name.ends_with("ToolIcon"))
            { label="repair tool"; panel="repair"; }
            if (!label.empty())
            {
                auto* data=w->getUserData<MWWorld::Ptr>(false);
                const bool occupied=w->getUserString("ToolTipType")=="ItemPtr" && data && !data->isEmpty();
                Entry e{label+": "+(occupied?std::string(data->getClass().getName(*data)):"empty"),"item_slot",clip,enabled,
                    [w,apparatus]{
                        // Empty apparatus icons in stock 0.51 may have no user data yet.
                        if (apparatus && !w->getUserData<MWWorld::Ptr>(false)) w->setUserData(MWWorld::Ptr());
                        w->eventMouseButtonClick(w);
                    }};
                e.panel=panel;
                if (occupied)
                {
                    e.count=data->getCellRef().getCount();
                    e.description=plain(MyGUI::LanguageManager::getInstance().replaceTags(data->getClass().getToolTipInfo(*data,e.count).text));
                }
                out.entries.push_back(std::move(e));
                return;
            }
        }
        if (w->getName().find("SneakBox")!=std::string::npos)
            out.entries.push_back({"Sneak indicator (HUD): hidden","indicator",clip,false,{}});
        if (w->isType<MWGui::Widgets::MWSpellEffect>())
        {
            // Copy of the rendered caption, including '?' for unknown ingredient effects.
            const auto caption=w->getUserString("AstraEffectText");
            if (!caption.empty()) out.entries.push_back({plain(MyGUI::UString(caption)),"text",clip,false,{}});
            return;
        }
        if (w->isType<MWGui::Widgets::MWSpell>())
        {
            const auto caption=w->getUserString("AstraSpellName");
            if (!caption.empty()) out.entries.push_back({plain(MyGUI::UString(caption)),"text",clip,false,{}});
            return;
        }
        if (auto* page=w->castType<MWGui::BookPage>(false))
        {
            const bool dialogue=inDialogue(w,wm);
            int previousTop=0,previousBottom=0;
            bool first=true;
            for (auto& run:page->astraVisibleRuns(!dialogue))
            {
                if (dialogue && !run.text.empty())
                {
                    out.dialogue=true;
                    if (!first && run.rect.top!=previousTop)
                        out.dialogueText+=run.rect.top>previousBottom+2 ? "\n\n" : "\n";
                    out.dialogueText+=run.text;
                    previousTop=run.rect.top;previousBottom=run.rect.bottom;first=false;
                }
                auto rect=intersection(clip,run.rect);
                if (run.text.empty() || (empty(rect) && (!dialogue || !run.link))) continue;
                const auto id=run.link;
                Entry e{run.text,id ? "link" : "text",rect,enabled && id!=0,
                    id ? std::function<void()>([page,id]{page->astraActivateLink(id);}) : std::function<void()>()};
                e.screenVisible=!empty(rect);
                e.panel="rich_text";out.entries.push_back(std::move(e));
            }
        }
        else if (auto* slider=w->castType<MyGUI::ScrollBar>(false))
        {
            const auto range=slider->getScrollRange();
            Entry e{"Ползунок","slider",clip,enabled && range>1,{}};
            e.sliderPosition=slider->getScrollPosition();e.sliderMax=range?range-1:0;
            e.adjust=[slider](std::size_t position) {
                slider->setScrollPosition(position);
                slider->eventScrollChangePosition(slider,slider->getScrollPosition());
            };
            out.entries.push_back(std::move(e));
            return; // The skin's thumb/arrows are parts of this same control.
        }
        else if (auto* bar=w->castType<MyGUI::ProgressBar>(false))
        {
            const bool enemy=w->getName().find("EnemyHealth")!=std::string::npos;
            const bool breath=w->getName().find("Drowning")!=std::string::npos;
            if ((enemy || breath) && bar->getProgressRange()>0)
            {
                const auto percent=100*bar->getProgressPosition()/bar->getProgressRange();
                out.entries.push_back({std::string(enemy?"Enemy health (HUD): ":"Breath (HUD): ")+std::to_string(percent)+"%","meter",clip,false,{}});
            }
        }
        else if (auto* text=w->castType<MyGUI::TextBox>(false))
        {
            std::string label=plain(text->getCaption());
            const bool button=w->isType<MyGUI::Button>();
            if (button && label.empty() && wm->containsMode(MWGui::GM_Race))
            {
                const auto& name=w->getName();
                for (const auto& part: {std::pair{"GenderButton","sRaceMenu2"},
                                      std::pair{"FaceButton","sRaceMenu3"},std::pair{"HairButton","sRaceMenu4"}})
                {
                    if (name.ends_with(std::string("Prev")+part.first))
                        label=std::string(wm->getGameSettingString(part.second,part.first))+" ←";
                    if (name.ends_with(std::string("Next")+part.first))
                        label=std::string(wm->getGameSettingString(part.second,part.first))+" →";
                }
            }
            const bool input=w->isType<MyGUI::EditBox>() && !w->castType<MyGUI::EditBox>()->getEditReadOnly()
                && !w->castType<MyGUI::EditBox>()->getEditStatic();
            if (!label.empty() || input)
            {
                Entry e{label,button?"button":input?"input":"text",clip,enabled && (button || input),
                    button ? std::function<void()>([w]{w->eventMouseButtonClick(w);}) : std::function<void()>()};
                e.unavailableReason=w->getUserString("AstraUnavailableReason");
                if (root(w)->getLayer() && root(w)->getLayer()->getName()=="Notification") e.panel="notification";
                if (button && wm->containsMode(MWGui::GM_Alchemy)
                    && (w->getName().ends_with("IncreaseButton") || w->getName().ends_with("DecreaseButton")))
                    e.action=[w]{
                        const auto r=w->getAbsoluteRect();
                        const int x=(r.left+r.right)/2,y=(r.top+r.bottom)/2;
                        w->eventMouseButtonPressed(w,x,y,MyGUI::MouseButton::Left);
                        w->eventMouseButtonReleased(w,x,y,MyGUI::MouseButton::Left);
                    };
                if (input) e.edit=[box=w->castType<MyGUI::EditBox>()](const std::string& value) {
                    box->setCaption(MyGUI::UString(value));
                    box->eventEditTextChange(box);
                };
                out.entries.push_back(std::move(e));
            }
        }
        else if (w->isType<Gui::ImageButton>())
        {
            // These native book/scroll controls use an image rather than a caption.
            std::string label;
            const auto& n=w->getName();
            if (n.find("TakeButton")!=std::string::npos) label=wm->getGameSettingString("sTake","Take");
            else if (n.find("CloseButton")!=std::string::npos) label=wm->getGameSettingString("sClose","Close");
            else if (n.ends_with("NextPageBTN")) label="Next page";
            else if (n.ends_with("PrevPageBTN")) label="Previous page";
            if (!label.empty()) out.entries.push_back({label,"button",clip,enabled,[w]{w->eventMouseButtonClick(w);}});
        }
        auto children=w->getEnumerator();
        while (children.next()) visit(children.current(),clip,modalRoot,wm,out,depth+1);
    }
    inline Snapshot snapshot(MWBase::WindowManager* wm)
    {
        Snapshot out;
        if (wm->isConsoleMode() || wm->isPostProcessorHudVisible())
        {out.revision="non_gameplay_ui";return out;}
        out.modal=MyGUI::InputManager::getInstance().isModalAny();
        auto* modalRoot=root(MyGUI::InputManager::getInstance().getKeyFocusWidget());
        if (out.modal)
        {
            auto modals=MyGUI::Gui::getInstance().getEnumerator();
            while (modals.next())
                if (modals.current()->getInheritedVisible() && modals.current()->getUserString("AstraModalTop")=="true")
                    modalRoot=modals.current();
        }
        auto size=MyGUI::RenderManager::getInstance().getViewSize();
        auto roots=MyGUI::Gui::getInstance().getEnumerator();
        while (roots.next())
        {
            auto* w=roots.current();
            if (!w->getLayer() || !w->getLayerNode()) continue;
            // Engine/debug consoles are not gameplay UI observations.
            if (w->getName().find("Console")!=std::string::npos || w->getName().find("Debug")!=std::string::npos) continue;
            visit(w,{0,0,size.width,size.height},modalRoot,wm,out);
        }
        std::uint64_t hash=1469598103934665603ull;
        auto feed=[&](const std::string& s){for (unsigned char c:s){hash^=c;hash*=1099511628211ull;}};
        feed(out.modal?"modal":"normal");
        feed(out.dialogueText);
        feed(out.documentRef);
        for (const auto& e:out.entries)
        {
            feed(e.role); feed(e.text); feed(e.instance);
            feed(std::to_string(e.rect.left)+","+std::to_string(e.rect.top)+","+std::to_string(e.rect.right)+","+std::to_string(e.rect.bottom));
            feed(e.enabled?"on":"off");
            feed(e.screenVisible?"visible":"offscreen");
            if (e.role=="list_item") feed(e.selected?"selected":"unselected");
            feed(e.unavailableReason);
            feed(e.panel);feed(e.description);feed(std::to_string(e.count));
            feed(std::to_string(e.conditionCurrent)+"/"+std::to_string(e.conditionMax));
            if (e.role=="slider") feed(std::to_string(e.sliderPosition)+"/"+std::to_string(e.sliderMax));
            feed(e.equipped?"equipped":"unequipped");feed(e.pendingTrade?"pending":"normal");
        }
        std::ostringstream value;value<<std::hex<<hash;out.revision=value.str();
        return out;
    }
    inline sol::table observe(sol::this_state state,MWBase::WindowManager* wm)
    {
        sol::state_view lua(state);
        Snapshot snap=snapshot(wm);
        sol::table result(lua,sol::create),entries(lua,sol::create);
        result["revision"]=snap.revision;result["modal"]=snap.modal;
        if (!snap.documentRef.empty())
        {
            sol::table document(lua,sol::create);
            document["ref"]=snap.documentRef; document["title"]=snap.documentTitle;
            document["kind"]=snap.documentKind;
            document["characters"]=MyGUI::UString(snap.documentText).size();
            result["document"]=document;
        }
        if (snap.dialogue)
        {
            sol::table dialogue(lua,sol::create);
            dialogue["text"]=snap.dialogueText;
            result["dialogue"]=dialogue;
        }
        for (std::size_t i=0;i<snap.entries.size();++i)
        {
            const auto& e=snap.entries[i];
            sol::table row(lua,sol::create),rect(lua,sol::create);
            row["text"]=e.text;row["role"]=e.role;row["enabled"]=e.enabled;
            row["screen_visible"]=e.screenVisible;
            if (e.role=="list_item") row["selected"]=e.selected;
            if (!e.unavailableReason.empty()) row["unavailable_reason"]=e.unavailableReason;
            if (!e.panel.empty()) row["panel"]=e.panel;
            if (e.role=="slider")
            {row["slider_position"]=e.sliderPosition;row["slider_max"]=e.sliderMax;}
            if (e.role=="item" || e.role=="item_slot")
            {
                row["count"]=e.count;row["description"]=e.description;
                if (!e.instance.empty()) row["instance"]=e.instance;
                row["equipped"]=e.equipped;row["pending_trade"]=e.pendingTrade;
                if (e.conditionCurrent>=0)
                { row["condition_current"]=e.conditionCurrent; row["condition_max"]=e.conditionMax; }
            }
            row["ref"]="ui_"+snap.revision+"_"+std::to_string(i);
            rect[1]=e.rect.left;rect[2]=e.rect.top;rect[3]=e.rect.right-e.rect.left;rect[4]=e.rect.bottom-e.rect.top;
            if (e.screenVisible) row["rect"]=rect;
            entries[i+1]=row;
        }
        result["elements"]=entries;
        return result;
    }
    inline sol::table read(sol::this_state state, MWBase::WindowManager* wm,
        const std::string& ref, int offset, int limit)
    {
        sol::state_view lua(state);
        sol::table result(lua,sol::create);
        const auto snap=snapshot(wm);
        if (snap.documentRef.empty()) { result["reason"]="document_not_open"; return result; }
        if (!ref.empty() && ref!=snap.documentRef) { result["reason"]="stale_document_ref"; return result; }
        const MyGUI::UString text(snap.documentText);
        if (offset<0 || static_cast<std::size_t>(offset)>text.size() || limit<1 || limit>8000)
        { result["reason"]="invalid_arguments"; return result; }
        const auto next=std::min(text.size(),static_cast<std::size_t>(offset)+limit);
        result["ref"]=snap.documentRef; result["title"]=snap.documentTitle; result["kind"]=snap.documentKind;
        result["text"]=text.substr(offset,next-offset).asUTF8();
        result["offset"]=offset; result["next_offset"]=next; result["characters"]=text.size();
        result["eof"]=next==text.size();
        return result;
    }
    inline sol::table playerState(sol::this_state state)
    {
        auto& env=MWBase::Environment::get();
        auto world=env.getWorld();
        const auto player=world->getPlayerPtr();
        auto mechanics=env.getMechanicsManager();
        sol::table result(sol::state_view(state),sol::create);
        result["animation_busy"]=mechanics->isAttackingOrSpell(player);
        result["casting"]=mechanics->isCastingSpell(player);
        result["sneaking"]=mechanics->isSneaking(player);
        result["submerged"]=world->isSubmerged(player);
        return result;
    }
    inline sol::table ownedItemInfo(sol::this_state state, const LObject& object)
    {
        sol::table out(sol::state_view(state),sol::create);
        const auto ptr=object.ptr();
        const auto player=MWBase::Environment::get().getWorld()->getPlayerPtr();
        auto& inventory=player.getClass().getInventoryStore(player);
        bool owned=false;
        for (auto it=inventory.begin();it!=inventory.end();++it) if (*it==ptr) { owned=true;break; }
        if (!owned) return out;
        const auto& cls=ptr.getClass();
        out["instance"]=itemIdentity(ptr);
        const auto tooltip=cls.getToolTipInfo(ptr,ptr.getCellRef().getCount());
        out["description"]=plain(MyGUI::LanguageManager::getInstance().replaceTags(tooltip.text));
        auto effects=tooltip.effects;
        if (cls.hasItemHealth(ptr))
        { out["condition_current"]=cls.getItemHealth(ptr);out["condition_max"]=cls.getItemMaxHealth(ptr); }
        if (ptr.getType()==ESM::Repair::sRecordId || ptr.getType()==ESM::Lockpick::sRecordId || ptr.getType()==ESM::Probe::sRecordId)
            out["uses_remaining"]=cls.getItemHealth(ptr);
        const auto enchantment=cls.getEnchantment(ptr);
        if (!enchantment.empty())
        {
            const auto* record=MWBase::Environment::get().getESMStore()->get<ESM::Enchantment>().find(enchantment);
            effects=MWGui::Widgets::MWEffectList::effectListFromESM(&record->mEffects);
            const float capacity=MWMechanics::getEnchantmentCharge(*record);
            const float charge=ptr.getCellRef().getEnchantmentCharge();
            if (record->mData.mType==ESM::Enchantment::WhenUsed || record->mData.mType==ESM::Enchantment::WhenStrikes)
            { out["charge_current"]=charge<0?capacity:charge;out["charge_max"]=capacity; }
        }
        if (!effects.empty())
        {
            sol::table list(sol::state_view(state),sol::create);
            const auto& store=*MWBase::Environment::get().getESMStore();
            int index=0;
            for (const auto& effect:effects)
            {
                sol::table row(sol::state_view(state),sol::create);
                if (!effect.mKnown || effect.mEffectID.empty()) row["name"]="?";
                else
                {
                    row["name"]=MWMechanics::getMagicEffectString(*store.get<ESM::MagicEffect>().find(effect.mEffectID),
                        store.get<ESM::Attribute>().search(effect.mAttribute),store.get<ESM::Skill>().search(effect.mSkill));
                    if (!tooltip.isIngredient)
                    {
                        if (effect.mMagnMin>=0) row["magnitude_min"]=effect.mMagnMin;
                        if (effect.mMagnMax>=0) row["magnitude_max"]=effect.mMagnMax;
                        if (effect.mDuration>=0) row["duration"]=effect.mDuration;
                    }
                }
                list[++index]=row;
            }
            out["effects"]=list;
        }
        return out;
    }
    inline std::string doorDescription(const LObject& object)
    {
        const auto ptr=object.ptr();
        if (ptr.getType()!=ESM::Door::sRecordId && ptr.getType()!=ESM::Container::sRecordId) return {};
        auto info=ptr.getClass().getToolTipInfo(ptr,1);
        return plain(MyGUI::LanguageManager::getInstance().replaceTags(info.caption+"\n"+info.text));
    }
    inline bool choose(MWBase::WindowManager* wm,const std::string& ref)
    {
        Snapshot snap=snapshot(wm);
        for (std::size_t i=0;i<snap.entries.size();++i)
        {
            auto& e=snap.entries[i];
            if (ref=="ui_"+snap.revision+"_"+std::to_string(i) && e.enabled && e.action)
            {e.action();return true;}
        }
        return false;
    }
    inline bool hover(MWBase::WindowManager* wm,const std::string& ref)
    {
        if (!wm->isGuiMode()) return false;
        const auto snap=snapshot(wm);
        for (std::size_t i=0;i<snap.entries.size();++i)
        {
            const auto& e=snap.entries[i];
            if (ref!="ui_"+snap.revision+"_"+std::to_string(i) || !e.screenVisible) continue;
            MWBase::Environment::get().getInputManager()->injectUiMouseMove(
                (e.rect.left+e.rect.right)/2,(e.rect.top+e.rect.bottom)/2);
            wm->setCursorActive(true);
            return true;
        }
        return false;
    }
    inline bool scroll(MWBase::WindowManager* wm,int steps)
    {
        if (!wm->isGuiMode() || wm->isConsoleMode() || wm->isPostProcessorHudVisible()
            || steps < -10 || steps > 10) return false;
        auto& input=MyGUI::InputManager::getInstance();
        for (int i=0;i<std::abs(steps);++i)
        {
            auto* w=input.getMouseFocusWidget();
            if (!w || !w->getInheritedVisible() || !w->getInheritedEnabled()) return false;
            if (input.isModalAny() && root(w)!=root(input.getKeyFocusWidget())) return false;
            // Normal MyGUI event dispatch, including widget overrides. One detent is 120.
            w->_riseMouseWheel(steps>0 ? 120 : -120);
        }
        return true;
    }
    inline bool edit(MWBase::WindowManager* wm,const std::string& ref,const std::string& value)
    {
        Snapshot snap=snapshot(wm);
        for (std::size_t i=0;i<snap.entries.size();++i)
        {
            auto& e=snap.entries[i];
            if (ref=="ui_"+snap.revision+"_"+std::to_string(i) && e.enabled && e.edit)
            {e.edit(value);return true;}
        }
        return false;
    }
    inline bool adjust(MWBase::WindowManager* wm,const std::string& ref,std::size_t position)
    {
        Snapshot snap=snapshot(wm);
        for (std::size_t i=0;i<snap.entries.size();++i)
        {
            auto& e=snap.entries[i];
            if (ref=="ui_"+snap.revision+"_"+std::to_string(i) && e.enabled && e.adjust && position<=e.sliderMax)
            {e.adjust(position);return true;}
        }
        return false;
    }
}
