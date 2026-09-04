import { useEffect, useState, useRef } from 'react'

const PROMPTS_BY_LANG = {
  en: [
    "What's the weather in Mumbai today?",
    "Will it rain in Delhi this week?",
    "7-day forecast for Bangalore",
    "Air quality index in Chennai",
    "Is it safe to go outside in Jaipur?",
    "UV index and heat advisory for Kolkata",
    "Should I carry an umbrella today?",
    "Weekend weather for Goa beach trip",
  ],
  hi: [
    "आज मुंबई में मौसम कैसा है?",
    "क्या इस हफ्ते दिल्ली में बारिश होगी?",
    "बैंगलोर का 7 दिनों का पूर्वानुमान",
    "चेन्नई में वायु गुणवत्ता सूचकांक (AQI)",
    "क्या जयपुर में आज बाहर जाना सुरक्षित है?",
    "कोलकाता के लिए UV इंडेक्स और सलाह",
    "क्या मुझे आज छाता ले जाना चाहिए?",
    "गोवा यात्रा के लिए सप्ताहांत का मौसम",
  ],
  gu: [
    "આજે મુંબઈમાં હવામાન કેવું છે?",
    "શું આ અઠવાડિયે દિલ્હીમાં વરસાદ પડશે?",
    "બેંગલુરુ માટે 7 દિવસનું પૂર્વાનુમાન",
    "ચેન્નાઈમાં હવાની ગુણવત્તા (AQI)",
    "જયપુરમાં આજે બહાર જવું સુરક્ષિત છે?",
    "કોલકાતા માટે UV ઇન્ડેક્સ અને સૂચના",
    "શું મારે આજે છત્રી રાખવી જોઈએ?",
    "ગોવા પ્રવાસ માટે વીકએન્ડ હવામાન",
  ],
  mr: [
    "आज मुंबईत हवामान कसे आहे?",
    "या आठवड्यात दिल्लीत पाऊस पडेल का?",
    "बंगळुरूसाठी ७ दिवसांचा अंदाज",
    "चेन्नईतील हवा गुणवत्ता निर्देशांक (AQI)",
    "जयपुरमध्ये आज बाहेर जाणे सुरक्षित आहे का?",
    "कोलकात्यासाठी UV इंडेक्स आणि सल्ला",
    "आज छत्री सोबत ठेवावी का?",
    "गोवा सहलीसाठी शनिवार-रविवारचे हवामान",
  ],
  bn: [
    "আজ মুম্বাইতে আবহাওয়া কেমন?",
    "এই সপ্তাহে দিল্লিতে কি বৃষ্টি হবে?",
    "ব্যাঙ্গালোরের ৭ দিনের আবহাওয়ার পূর্বাভাস",
    "চেন্নাইয়ের বায়ুর গুণমান সূচক (AQI)",
    "জয়পুরে আজ বাইরে যাওয়া কি নিরাপদ?",
    "কলকাতার জন্য UV সূচক ও সতর্কতা",
    "আজ কি ছাতা সাথে নেওয়া উচিত?",
    "গোয়া ভ্রমণের উইকেন্ড পূর্বাভাস",
  ],
  ta: [
    "இன்று மும்பையில் வானிலை எப்படி இருக்கிறது?",
    "இந்த வாரம் டெல்லியில் மழை பெய்யுமா?",
    "பெங்களூருக்கான 7 நாள் வானிலை அறிக்கை",
    "சென்னையில் காற்றுத் தரம் (AQI)",
    "ஜெய்ப்பூரில் இன்று வெளியே செல்வது பாதுகாப்பானதா?",
    "கொல்கத்தாவுக்கான UV குறியீடு மற்றும் எச்சரிக்கை",
    "இன்று குடை எடுத்துச் செல்ல வேண்டுமா?",
    "கோவா சுற்றுப்பயணத்திற்கான வார இறுதி வானிலை",
  ],
  te: [
    "ఈ రోజు ముంబైలో వాతావరణం ఎలా ఉంది?",
    "ఈ వారం ఢిల్లీలో వర్షం పడుతుందా?",
    "బెంగళూరు 7 రోజుల వాతావరణ సమాచారం",
    "చెన్నైలో గాలి నాణ్యత సూచిక (AQI)",
    "జైపూర్‌లో ఈ రోజు బయటకు వెళ్లడం సురక్షితమేనా?",
    "కోల్‌కతా UV సూచిక మరియు జాగ్రత్తలు",
    "ఈ రోజు గొడుగు తీసుకెళ్లాలా?",
    "గోవా ట్రిప్ వారాంతపు వాతావరణం",
  ],
}

export default function PromptRotator({ onSelectPrompt, langCode = 'en' }) {
  const prompts = PROMPTS_BY_LANG[langCode] || PROMPTS_BY_LANG.en

  const [box1, setBox1] = useState({
    currentText: prompts[0],
    nextText: '',
    isAnimating: false,
  })

  const [box2, setBox2] = useState({
    currentText: prompts[1] || prompts[0],
    nextText: '',
    isAnimating: false,
  })

  const activeTextsRef = useRef([prompts[0], prompts[1] || prompts[0]])

  // Reset prompts when langCode changes
  useEffect(() => {
    const newPrompts = PROMPTS_BY_LANG[langCode] || PROMPTS_BY_LANG.en
    setBox1({ currentText: newPrompts[0], nextText: '', isAnimating: false })
    setBox2({ currentText: newPrompts[1] || newPrompts[0], nextText: '', isAnimating: false })
    activeTextsRef.current = [newPrompts[0], newPrompts[1] || newPrompts[0]]
  }, [langCode])

  const getRandomPromptExcept = (exclude) => {
    const currentPrompts = PROMPTS_BY_LANG[langCode] || PROMPTS_BY_LANG.en
    const available = currentPrompts.filter((p) => !exclude.includes(p))
    if (available.length === 0) return currentPrompts[0]
    return available[Math.floor(Math.random() * available.length)]
  }

  // Box 1 independent rotation loop
  useEffect(() => {
    let timeoutId

    const triggerRotation = () => {
      const nextInterval = Math.random() * 3000 + 3000

      timeoutId = setTimeout(() => {
        const nextPrompt = getRandomPromptExcept(activeTextsRef.current)
        activeTextsRef.current[0] = nextPrompt

        setBox1((prev) => ({ ...prev, nextText: nextPrompt, isAnimating: true }))

        setTimeout(() => {
          setBox1(() => ({
            currentText: nextPrompt,
            nextText: '',
            isAnimating: false,
          }))
        }, 600)

        triggerRotation()
      }, nextInterval)
    }

    triggerRotation()
    return () => clearTimeout(timeoutId)
  }, [])

  // Box 2 independent rotation loop
  useEffect(() => {
    let timeoutId

    const triggerRotation = () => {
      const nextInterval = Math.random() * 3000 + 3000

      timeoutId = setTimeout(() => {
        const nextPrompt = getRandomPromptExcept(activeTextsRef.current)
        activeTextsRef.current[1] = nextPrompt

        setBox2((prev) => ({ ...prev, nextText: nextPrompt, isAnimating: true }))

        setTimeout(() => {
          setBox2(() => ({
            currentText: nextPrompt,
            nextText: '',
            isAnimating: false,
          }))
        }, 600)

        triggerRotation()
      }, nextInterval)
    }

    triggerRotation()
    return () => clearTimeout(timeoutId)
  }, [])

  const renderBox = (boxState, onSelect) => {
    return (
      <div
        className="relative h-9 w-[190px] sm:w-[240px] select-none"
        style={{ perspective: '1000px' }}
      >
        <div
          onClick={boxState.isAnimating ? undefined : onSelect}
          className="w-full h-full cursor-pointer relative"
          style={{
            transformStyle: 'preserve-3d',
            transform: boxState.isAnimating ? 'rotateX(90deg)' : 'rotateX(0deg)',
            transition: boxState.isAnimating
              ? 'transform 600ms cubic-bezier(0.4, 0, 0.2, 1)'
              : 'none',
          }}
        >
          {/* Front Face */}
          <div
            className="absolute inset-0 flex items-center justify-center px-3 rounded-lg border border-dotted border-white/20 bg-neutral-950 hover:bg-neutral-900 hover:border-white/40 transition-colors text-[11px] sm:text-xs text-white/70 hover:text-white text-center font-medium whitespace-nowrap overflow-hidden text-ellipsis"
            style={{
              backfaceVisibility: 'hidden',
              transform: 'rotateX(0deg) translateZ(18px)',
            }}
          >
            {boxState.currentText}
          </div>

          {/* Bottom Face (rolls up) */}
          <div
            className="absolute inset-0 flex items-center justify-center px-3 rounded-lg border border-dotted border-white/20 bg-neutral-950 text-[11px] sm:text-xs text-white/75 text-center font-medium whitespace-nowrap overflow-hidden text-ellipsis"
            style={{
              backfaceVisibility: 'hidden',
              transform: 'rotateX(-90deg) translateZ(18px)',
            }}
          >
            {boxState.nextText || boxState.currentText}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center gap-3 w-full py-1">
      {renderBox(box1, () => onSelectPrompt(box1.currentText))}
      {renderBox(box2, () => onSelectPrompt(box2.currentText))}
    </div>
  )
}
